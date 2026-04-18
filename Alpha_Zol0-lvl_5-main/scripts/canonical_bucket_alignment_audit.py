import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
if str(WORKDIR) not in sys.path:
    sys.path.insert(0, str(WORKDIR))

from scripts.canonical_bucket_identity import build_canonical_bucket_key


DIAG_DIR = WORKDIR / "artifacts" / "diagnostics"
DIAG_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_int(value, default=0):
    try:
        if value is None or isinstance(value, bool):
            return default
        return int(value)
    except Exception:
        return default


def _safe_float(value, default=0.0):
    try:
        if value is None or isinstance(value, bool):
            return default
        return float(value)
    except Exception:
        return default


def _normalize_side(value: str | None) -> str:
    txt = str(value or "").strip().lower()
    if txt in {"long", "buy"}:
        return "buy"
    if txt in {"short", "sell"}:
        return "sell"
    return txt or "unknown"


def _load_logs(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "select id, timestamp, event, details from logs order by id asc"
        ).fetchall()
    finally:
        conn.close()
    out = []
    for row in rows:
        try:
            payload = json.loads(row["details"]) if row["details"] else {}
        except Exception:
            payload = {"raw_details": row["details"]}
        out.append(
            {
                "id": int(row["id"]),
                "timestamp": str(row["timestamp"]),
                "event": str(row["event"]),
                "details": payload if isinstance(payload, dict) else {},
            }
        )
    return out


def _select_run(result_path: str | None, results_dir: Path) -> dict:
    if result_path:
        path = Path(result_path)
        if not path.is_absolute():
            path = (WORKDIR / path).resolve()
        payload = _load_json(path)
        before = payload.get("before") or {}
        db_path = Path(str(before.get("db_path") or "")).expanduser()
        if not db_path.is_absolute():
            db_path = (WORKDIR / db_path).resolve()
        return {
            "run_id": str(payload.get("run_id") or path.stem.replace("controlled_kpi_", "")),
            "results_path": str(path),
            "db_path": db_path,
            "duration_sec_actual": _safe_float(before.get("duration_sec_actual"), 0.0),
            "before": before,
        }

    candidates = []
    for path in sorted(results_dir.glob("controlled_kpi_*.json")):
        try:
            payload = _load_json(path)
        except Exception:
            continue
        before = payload.get("before") or {}
        if str(before.get("variant") or "") != "before":
            continue
        db_path = Path(str(before.get("db_path") or "")).expanduser()
        if not db_path.is_absolute():
            db_path = (WORKDIR / db_path).resolve()
        if not db_path.exists():
            continue
        candidates.append(
            {
                "run_id": str(payload.get("run_id") or path.stem.replace("controlled_kpi_", "")),
                "results_path": str(path),
                "db_path": db_path,
                "duration_sec_actual": _safe_float(before.get("duration_sec_actual"), 0.0),
                "before": before,
            }
        )
    if not candidates:
        raise FileNotFoundError("No controlled_kpi before runs found")
    candidates.sort(key=lambda r: (r["duration_sec_actual"], r["results_path"]))
    return candidates[-1]


def _row_payload_for_canonical(row: dict) -> dict:
    event = row["event"]
    details = row["details"] or {}
    if event == "entry_gate_decision_summary":
        payload = dict(details)
        if "strategy" not in payload and isinstance(payload.get("entry_edge_over_fee"), dict):
            payload["strategy"] = payload["entry_edge_over_fee"].get("strategy")
        return payload
    if event == "position_close":
        pos = details.get("position") or {}
        return {
            "symbol": details.get("symbol") or pos.get("symbol"),
            "side": pos.get("side") or details.get("side"),
            "position": pos,
            "strategy": (
                pos.get("entry_main_strategy")
                or pos.get("strategy")
                or details.get("main_strategy")
            ),
        }
    return details


def _build_report(result_path: str | None = None, results_dir: str | None = None) -> dict:
    run = _select_run(result_path, Path(results_dir or WORKDIR / "results"))
    logs = _load_logs(run["db_path"])

    evaluated_total = 0
    evaluated_resolved = 0
    evaluated_unresolved = 0
    close_total = 0
    close_resolved = 0
    close_unresolved = 0

    eval_resolved_keys = Counter()
    close_resolved_keys = Counter()
    eval_unresolved_reasons = Counter()
    close_unresolved_reasons = Counter()

    for row in logs:
        if row["event"] == "entry_gate_decision_summary":
            evaluated_total += 1
            canonical = build_canonical_bucket_key(_row_payload_for_canonical(row))
            if canonical["bucket_identity_status"] == "RESOLVED":
                evaluated_resolved += 1
                eval_resolved_keys[canonical["canonical_bucket_key"]] += 1
            else:
                evaluated_unresolved += 1
                eval_unresolved_reasons[canonical["bucket_identity_reason"]] += 1
        elif row["event"] == "position_close":
            close_total += 1
            canonical = build_canonical_bucket_key(_row_payload_for_canonical(row))
            if canonical["bucket_identity_status"] == "RESOLVED":
                close_resolved += 1
                close_resolved_keys[canonical["canonical_bucket_key"]] += 1
            else:
                close_unresolved += 1
                close_unresolved_reasons[canonical["bucket_identity_reason"]] += 1

    resolved_eval_unique = set(eval_resolved_keys)
    resolved_close_unique = set(close_resolved_keys)
    resolved_intersection = resolved_eval_unique & resolved_close_unique
    resolved_alignment_rate = (
        len(resolved_intersection) / max(1, min(len(resolved_eval_unique), len(resolved_close_unique)))
    )

    unresolved_share = (
        (evaluated_unresolved + close_unresolved)
        / max(1, evaluated_total + close_total)
    )
    evaluated_resolved_share = evaluated_resolved / max(1, evaluated_total)
    close_resolved_share = close_resolved / max(1, close_total)

    alignment = {
        "resolved_alignment_rate": resolved_alignment_rate,
        "unresolved_share": unresolved_share,
        "evaluated_resolved_share": evaluated_resolved_share,
        "close_resolved_share": close_resolved_share,
        "resolved_intersection_keys": sorted(resolved_intersection),
    }

    unresolved_reasons = {
        "missing_entry_edge_payload": int(eval_unresolved_reasons.get("missing_entry_edge_payload_or_strategy", 0)),
        "missing_strategy_field": int(
            eval_unresolved_reasons.get("missing_strategy_field", 0)
            + close_unresolved_reasons.get("missing_strategy_field", 0)
        ),
        "strategy_is___ALL__": int(
            eval_unresolved_reasons.get("strategy_is___ALL__", 0)
            + close_unresolved_reasons.get("strategy_is___ALL__", 0)
        ),
        "fallback_unknown": int(
            eval_unresolved_reasons.get("fallback_unknown", 0)
            + close_unresolved_reasons.get("fallback_unknown", 0)
        ),
    }

    readiness_alignment_improved = bool(resolved_alignment_rate > 0.7 and evaluated_resolved_share > 0.5)
    readiness_unlock_feasible = bool(resolved_alignment_rate > 0.7 and evaluated_resolved_share > 0.5 and close_resolved_share > 0.5)

    conclusion = {
        "readiness_alignment_improved": readiness_alignment_improved,
        "readiness_unlock_feasible": readiness_unlock_feasible,
    }

    evaluated_path = {
        "evaluated_bucket_fields": [
            "symbol",
            "entry_edge_over_fee.strategy",
            "strategy (shadow added field)",
            "side",
        ],
        "unknown_fallback_rules": [
            "entry_edge_over_fee missing",
            "strategy missing",
            "strategy == '__ALL__'",
            "fallback to unresolved status, not canonical identity",
        ],
        "strategy_normalization_rules": [
            "strategy.upper()",
            "symbol.upper()",
            "side.lower()",
        ],
        "dominant_evaluated_buckets": [
            {"bucket_key": key, "rows": count}
            for key, count in eval_resolved_keys.most_common(5)
        ],
    }

    close_path = {
        "close_bucket_fields": [
            "symbol",
            "position.entry_main_strategy",
            "strategy (shadow added field)",
            "side",
        ],
        "close_write_source_event": "position_close",
        "close_write_function_path": "_update_symbol_strategy_side_edge_perf",
        "dominant_close_buckets": [
            {"bucket_key": key, "rows": count}
            for key, count in close_resolved_keys.most_common(5)
        ],
    }

    return {
        "metadata": {
            "stamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
            "symbols": ["BTCUSDTM", "ETHUSDTM"],
            "scenarios": ["baseline", "disable_current_side", "disable_net_target_guard"],
            "method_version": "v1",
        },
        "coverage": {
            "evaluated_total": evaluated_total,
            "evaluated_resolved": evaluated_resolved,
            "evaluated_unresolved": evaluated_unresolved,
            "close_total": close_total,
            "close_resolved": close_resolved,
            "close_unresolved": close_unresolved,
        },
        "alignment": alignment,
        "unresolved_reasons": unresolved_reasons,
        "evaluated_path": evaluated_path,
        "close_write_path": close_path,
        "conclusion": conclusion,
        "final_classification": (
            "EVALUATION_HISTORY_PATHS_ARE_ARCHITECTURALLY_ALIGNED"
            if readiness_unlock_feasible
            else (
                "EVALUATION_HISTORY_PATHS_ARE_PARTIALLY_MISALIGNED"
                if resolved_alignment_rate > 0.0
                else "EVALUATION_HISTORY_PATHS_ARE_ARCHITECTURALLY_MISALIGNED"
            )
        ),
    }


def _render_md(report: dict) -> str:
    lines = []
    lines.append("## A. Executive Summary")
    lines.append(
        "The canonical bucket identity layer is research-only and additive. It makes resolved bucket identity explicit on both evaluated and close-write paths while keeping unresolved rows visible instead of collapsing them into canonical readiness buckets."
    )
    lines.append("")
    lines.append("## B. Scope")
    lines.append("- PAPER only")
    lines.append("- Audit-only")
    lines.append("- No runtime decision changes")
    lines.append("- No storage schema changes")
    lines.append("- No proxy")
    lines.append("")
    lines.append("## C. Canonical Identity Rules")
    lines.append(f"- evaluated bucket fields: {', '.join(report['evaluated_path']['evaluated_bucket_fields'])}")
    lines.append(f"- close bucket fields: {', '.join(report['close_write_path']['close_bucket_fields'])}")
    lines.append(f"- strategy normalization: {', '.join(report['evaluated_path']['strategy_normalization_rules'])}")
    lines.append(f"- unknown fallback rules: {', '.join(report['evaluated_path']['unknown_fallback_rules'])}")
    lines.append("")
    lines.append("## D. Evaluated Path Coverage")
    c = report["coverage"]
    lines.append(f"- total: {c['evaluated_total']}")
    lines.append(f"- resolved: {c['evaluated_resolved']}")
    lines.append(f"- unresolved: {c['evaluated_unresolved']}")
    lines.append("")
    lines.append("## E. Close Path Coverage")
    lines.append(f"- total: {c['close_total']}")
    lines.append(f"- resolved: {c['close_resolved']}")
    lines.append(f"- unresolved: {c['close_unresolved']}")
    lines.append("")
    lines.append("## F. Alignment Metrics")
    a = report["alignment"]
    lines.append(f"- resolved_alignment_rate: {a['resolved_alignment_rate']:.6f}")
    lines.append(f"- unresolved_share: {a['unresolved_share']:.6f}")
    lines.append(f"- evaluated_resolved_share: {a['evaluated_resolved_share']:.6f}")
    lines.append(f"- close_resolved_share: {a['close_resolved_share']:.6f}")
    lines.append("")
    lines.append("## G. Unresolved Population Analysis")
    for k, v in report["unresolved_reasons"].items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## H. Architectural Impact")
    lines.append(
        "If the redesign is carried forward, resolved buckets can be compared directly while unresolved rows remain explicit. That is an architectural improvement, but it is only useful if future runs actually populate `strategy` on the evaluated path."
    )
    lines.append("")
    lines.append("## I. Readiness Unlock Feasibility")
    lines.append(
        "In the current state of the corpus, the redesign is feasible as a research rollout, but the alignment thresholds are not yet strong enough to claim an unlock."
    )
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit canonical bucket identity alignment.")
    parser.add_argument("--result-path", default=None)
    parser.add_argument("--results-dir", default=str(WORKDIR / "results"))
    args = parser.parse_args(argv)
    report = _build_report(args.result_path, args.results_dir)
    stamp = report["metadata"]["stamp"]
    json_path = DIAG_DIR / f"canonical_bucket_alignment_{stamp}.json"
    md_path = DIAG_DIR / f"canonical_bucket_alignment_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
