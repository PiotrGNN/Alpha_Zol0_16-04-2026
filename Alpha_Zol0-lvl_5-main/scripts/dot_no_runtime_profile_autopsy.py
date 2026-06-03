from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WORKDIR = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = WORKDIR / "analysis"


def _split_key(key: str) -> dict[str, str]:
    parts = [part.strip() for part in str(key or "").split(":")]
    if len(parts) != 3:
        return {"symbol": "", "strategy": "", "side": ""}
    return {
        "symbol": parts[0].upper(),
        "strategy": parts[1],
        "side": parts[2].lower(),
    }


def _canonical_strategy(value: Any) -> str:
    text = "".join(ch for ch in str(value or "").upper() if ch.isalnum())
    if text.endswith("V2"):
        text = text[:-2]
    return text


def _canonical_key(key: str) -> str:
    parsed = _split_key(key)
    if not parsed["symbol"] or not parsed["strategy"] or not parsed["side"]:
        return ""
    return (
        f"{parsed['symbol']}:"
        f"{_canonical_strategy(parsed['strategy'])}:"
        f"{parsed['side']}"
    )


def _row_key(row: dict[str, Any]) -> str:
    symbol = str(row.get("symbol") or "").strip().upper()
    strategy = str(row.get("strategy") or "").strip()
    side = str(row.get("side") or "").strip().lower()
    if not symbol or not strategy or side not in {"buy", "sell"}:
        return ""
    return f"{symbol}:{strategy}:{side}"


def classify_profile_autopsy(
    *,
    research_key: str,
    allowlist_key: str,
    runtime_symbols: list[str],
    runtime_profile_rows: list[dict[str, Any]],
    gate_reason_distribution: dict[str, int],
    alpha_history_candidate_present: bool,
) -> dict[str, Any]:
    research = _split_key(research_key)
    allowlist = _split_key(allowlist_key)
    normalized_research = _canonical_key(research_key)
    normalized_allowlist = _canonical_key(allowlist_key)
    runtime_symbol_set = {str(symbol or "").strip().upper() for symbol in runtime_symbols}
    matching_profile_rows = [
        row
        for row in runtime_profile_rows
        if _canonical_key(_row_key(row)) == normalized_research
    ]
    strategy_mismatch = bool(
        research.get("symbol")
        and allowlist.get("symbol") == research.get("symbol")
        and allowlist.get("side") == research.get("side")
        and _canonical_strategy(allowlist.get("strategy"))
        != _canonical_strategy(research.get("strategy"))
    )
    if research.get("symbol") not in runtime_symbol_set:
        classification = "DOT_SYMBOL_UNIVERSE_MISSING"
        patch_decision = "runtime_universe_excludes_selected_research_symbol"
    elif normalized_allowlist and normalized_allowlist != normalized_research:
        classification = "DOT_ALLOWLIST_TOKEN_MISMATCH"
        patch_decision = "allowlist_token_strategy_name_mismatch"
    elif strategy_mismatch:
        classification = "DOT_STRATEGY_NAME_MISMATCH"
        patch_decision = "allowlist_token_strategy_name_mismatch"
    elif matching_profile_rows:
        if int(gate_reason_distribution.get("entry_min_net_guard") or 0) > 0:
            classification = "DOT_PROFILE_EXISTS_BUT_MIN_NET_GUARD_BLOCKED"
        elif int(gate_reason_distribution.get("entry_edge_filtered") or 0) > 0:
            classification = "DOT_PROFILE_EXISTS_BUT_ENTRY_EDGE_FILTERED"
        else:
            classification = "DOT_RUNTIME_PROFILE_AUTOPSY_INCONCLUSIVE"
        patch_decision = "not_justified"
    elif not alpha_history_candidate_present:
        classification = "DOT_PROFILE_NOT_HYDRATED_FROM_RESEARCH_DISCOVERY"
        patch_decision = "research_discovery_to_runtime_profile_bridge_missing"
    else:
        classification = "DOT_RUNTIME_PROFILE_AUTOPSY_INCONCLUSIVE"
        patch_decision = "not_justified"
    return {
        "classification": classification,
        "patch_decision": patch_decision,
        "normalization": {
            "research_key": research_key,
            "allowlist_key": allowlist_key,
            "canonical_research_key": normalized_research,
            "canonical_allowlist_key": normalized_allowlist,
            "allowlist_matches_research": bool(
                normalized_research and normalized_research == normalized_allowlist
            ),
            "strategy_name_mismatch": bool(strategy_mismatch),
            "symbol_in_runtime_universe": research.get("symbol") in runtime_symbol_set,
        },
        "runtime_profile": {
            "matching_profile_row_count": len(matching_profile_rows),
            "sample_rows": matching_profile_rows[:5],
        },
    }


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _gate_reason_distribution(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        out: Counter[str] = Counter()
        for row in conn.execute(
            "SELECT details FROM logs WHERE event='entry_gate_decision_summary'"
        ):
            try:
                payload = json.loads(row["details"] or "{}")
            except Exception:
                continue
            reason = str(
                payload.get("local_gate_reason")
                or payload.get("effective_gate_reason")
                or ""
            )
            out[reason] += 1
        return dict(out)
    finally:
        conn.close()


def _runtime_profile_rows(db_path: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows: list[dict[str, Any]] = []
        for row in conn.execute(
            "SELECT id, timestamp, event, details FROM logs "
            "WHERE event IN ('entry_eval_v2','entry_reject_v2','entry_gate_decision_summary') "
            "ORDER BY id ASC"
        ):
            try:
                payload = json.loads(row["details"] or "{}")
            except Exception:
                continue
            if payload.get("runtime_profile_key") is None:
                continue
            rows.append(
                {
                    "id": row["id"],
                    "timestamp": row["timestamp"],
                    "event": row["event"],
                    "symbol": payload.get("symbol"),
                    "strategy": payload.get("strategy"),
                    "side": payload.get("side"),
                    "runtime_profile_source": payload.get("runtime_profile_source"),
                    "runtime_profile_key": payload.get("runtime_profile_key"),
                    "runtime_profile_sample_size": payload.get(
                        "runtime_profile_sample_size"
                    ),
                    "runtime_profile_span_sec": payload.get(
                        "runtime_profile_span_sec"
                    ),
                    "expected_net_after_cost": (
                        payload.get("expected_net_after_cost")
                        or (payload.get("entry_edge_after_execution") or {}).get(
                            "expected_net_after_cost"
                        )
                    ),
                    "reason_code": payload.get("reason_code")
                    or payload.get("local_gate_reason"),
                    "risk_block_fields": payload.get("risk_block_fields") or {},
                }
            )
        return rows
    finally:
        conn.close()


def _alpha_history_candidate_present(path: Path, research_key: str) -> bool:
    if not path.exists():
        return False
    data = _load_json(path)
    target = _canonical_key(research_key)
    for section in ("pair_side_stats_top", "pair_stats_top"):
        for row in data.get(section) or []:
            key = _row_key(row)
            if key and _canonical_key(key) == target:
                return True
    return False


def build_report(
    *,
    research_artifact: Path,
    smoke_artifact: Path,
    result_artifact: Path,
    alpha_history_report: Path,
) -> dict[str, Any]:
    research = _load_json(research_artifact)
    smoke = _load_json(smoke_artifact)
    result = _load_json(result_artifact)
    best = research.get("single_best_hypothesis") or {}
    research_key = str(best.get("candidate_key") or "")
    allowlist_key = str(
        (smoke.get("exact_environment") or {}).get(
            "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST"
        )
        or ""
    )
    after = result.get("after") or {}
    params = result.get("params") or {}
    db_path = Path(after.get("db_path") or smoke.get("db_path") or "")
    runtime_profile_rows = _runtime_profile_rows(db_path) if db_path.exists() else []
    gates = _gate_reason_distribution(db_path) if db_path.exists() else {}
    alpha_present = _alpha_history_candidate_present(alpha_history_report, research_key)
    classified = classify_profile_autopsy(
        research_key=research_key,
        allowlist_key=allowlist_key,
        runtime_symbols=list(params.get("symbols") or []),
        runtime_profile_rows=runtime_profile_rows,
        gate_reason_distribution=gates,
        alpha_history_candidate_present=alpha_present,
    )
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "target": "DOTUSDTM:TrendFollowingV2:sell",
        "source_artifacts": {
            "research_artifact": str(research_artifact),
            "smoke_artifact": str(smoke_artifact),
            "result_artifact": str(result_artifact),
            "runtime_db": str(db_path),
            "alpha_history_report": str(alpha_history_report),
        },
        "research_candidate": best,
        "runtime_profile_sources": {
            "runtime_symbols": list(params.get("symbols") or []),
            "alpha_history_candidate_present": bool(alpha_present),
            "bootstrap_rows_inserted": (
                result.get("alpha_bootstrap_refresh") or {}
            ).get("report", {}).get("rows_inserted"),
            "positive_side_allowlist": (
                result.get("entry_admission_contract") or {}
            ).get("positive_side_allowlist"),
            "runtime_profile_source_values": sorted(
                {
                    str(row.get("runtime_profile_source"))
                    for row in runtime_profile_rows
                    if row.get("runtime_profile_source") is not None
                }
            ),
        },
        "canonical_key_formats": classified["normalization"],
        "gate_path": {
            "gate_reason_distribution": gates,
            "profile_row_count": len(runtime_profile_rows),
            "matching_profile_row_count": classified["runtime_profile"][
                "matching_profile_row_count"
            ],
            "matching_profile_sample_rows": classified["runtime_profile"][
                "sample_rows"
            ],
        },
        "classification": classified["classification"],
        "patch_decision": classified["patch_decision"],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# DOT No Runtime Profile Autopsy",
        "",
        f"- generated_at_utc: `{report.get('generated_at_utc')}`",
        f"- target: `{report.get('target')}`",
        f"- classification: `{report.get('classification')}`",
        f"- patch_decision: `{report.get('patch_decision')}`",
        "",
        "## Canonical Keys",
    ]
    for key, value in (report.get("canonical_key_formats") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Runtime Profile Sources"])
    for key, value in (report.get("runtime_profile_sources") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Gate Path"])
    gate_path = report.get("gate_path") or {}
    lines.append(f"- gate_reason_distribution: `{gate_path.get('gate_reason_distribution')}`")
    lines.append(f"- profile_row_count: `{gate_path.get('profile_row_count')}`")
    lines.append(
        f"- matching_profile_row_count: `{gate_path.get('matching_profile_row_count')}`"
    )
    lines.extend(["", "## Matching Profile Sample Rows"])
    for row in gate_path.get("matching_profile_sample_rows") or []:
        lines.append(f"- `{row}`")
    return "\n".join(lines).strip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only DOT runtime profile autopsy")
    parser.add_argument(
        "--research-artifact",
        default=str(ANALYSIS_DIR / "new_alpha_search_space_inventory_current.json"),
    )
    parser.add_argument(
        "--smoke-artifact",
        default=str(ANALYSIS_DIR / "dot_trendfollowingv2_runtime_smoke_current.json"),
    )
    parser.add_argument(
        "--result-artifact",
        default=str(WORKDIR / "results" / "controlled_kpi_20260603_142706.json"),
    )
    parser.add_argument(
        "--alpha-history-report",
        default=str(WORKDIR / "tmp" / "alpha_history_auto_recent_report.json"),
    )
    parser.add_argument(
        "--output-json",
        default=str(ANALYSIS_DIR / "dot_no_runtime_profile_autopsy_current.json"),
    )
    parser.add_argument(
        "--output-md",
        default=str(ANALYSIS_DIR / "dot_no_runtime_profile_autopsy_current.md"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(
        research_artifact=Path(args.research_artifact),
        smoke_artifact=Path(args.smoke_artifact),
        result_artifact=Path(args.result_artifact),
        alpha_history_report=Path(args.alpha_history_report),
    )
    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    output_md.write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "classification": report["classification"],
                "patch_decision": report["patch_decision"],
                "output_json": str(output_json),
                "output_md": str(output_md),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
