import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


WORKDIR = Path(__file__).resolve().parents[1]
DIAG_DIR = WORKDIR / "artifacts" / "diagnostics"
DIAG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_SHADOW = DIAG_DIR / "proxy_readiness_shadow_only_20260328_015643.json"
DEFAULT_DB_PATHS = [
    WORKDIR / "tmp" / "controlled_kpi_before_20260328_010209.db",
    WORKDIR / "tmp" / "controlled_kpi_before_20260328_010418.db",
    WORKDIR / "tmp" / "controlled_kpi_before_20260328_011249.db",
]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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
                "details": payload,
            }
        )
    return out


def _db_key(path: Path) -> tuple[str, str]:
    name = path.name
    if "010209" in name:
        return ("BTCUSDTM", "baseline")
    if "010418" in name:
        return ("BTCUSDTM", "disable_current_side")
    if "011249" in name:
        return ("ETHUSDTM", "disable_current_side")
    return ("unknown", "unknown")


def _realized_summary(events: list[dict]) -> dict:
    entry_rows = [e for e in events if e["event"] == "entry_gate_decision_summary"]
    close_rows = [e for e in events if e["event"] == "position_close"]
    realized_rows = [e for e in events if e["event"] == "realized_outcome_per_side"]
    realized_pnls = []
    for row in realized_rows:
        realized_pnls.append(float(row["details"].get("realized_net_pnl") or 0.0))
    if realized_pnls:
        mean_realized = sum(realized_pnls) / len(realized_pnls)
    else:
        mean_realized = None
    return {
        "entry_rows": len(entry_rows),
        "close_rows": len(close_rows),
        "realized_rows": len(realized_rows),
        "mean_realized_net_pnl": mean_realized,
        "realized_sign": (
            "positive" if mean_realized is not None and mean_realized > 0 else "negative"
            if mean_realized is not None and mean_realized < 0
            else "flat_or_missing"
        ),
        "first_close_ts": close_rows[0]["timestamp"] if close_rows else None,
        "first_realized_ts": realized_rows[0]["timestamp"] if realized_rows else None,
    }


def _proxy_shadow_summary(shadow_report: dict, symbol: str, scenario: str) -> dict:
    payload = (shadow_report.get("per_symbol", {}).get(symbol, {}) or {}).get(scenario, {})
    shadow_rows = payload.get("shadow_rows") or []
    shadow_scores = [1.0 if bool(r.get("shadow_ready")) else 0.0 for r in shadow_rows]
    shadow_ready_count = sum(1 for v in shadow_scores if v > 0.0)
    if shadow_scores:
        mean_shadow = sum(shadow_scores) / len(shadow_scores)
    else:
        mean_shadow = 0.0
    return {
        "rows": int(payload.get("rows", 0)),
        "proxy_shadow_trade_count": int(payload.get("proxy_shadow_trade_count", 0)),
        "proxy_shadow_history_ready": bool(payload.get("proxy_shadow_history_ready")),
        "proxy_shadow_edge_mean": float(payload.get("proxy_shadow_edge_mean") or mean_shadow),
        "earlier_observability_gain": bool(payload.get("earlier_observability_gain")),
        "shadow_ready_count": shadow_ready_count,
    }


def _build_report(shadow_path: Path, db_paths: list[Path]) -> dict:
    shadow = _load_json(shadow_path)
    realized_map = {}
    for db_path in db_paths:
        symbol, scenario = _db_key(db_path)
        realized_map[(symbol, scenario)] = _realized_summary(_load_logs(db_path))

    pairs = []
    corpus_proxy_positive_count = 0
    corpus_proxy_positive_realized_negative_count = 0
    for (symbol, scenario), realized in realized_map.items():
        proxy = _proxy_shadow_summary(shadow, symbol, scenario)
        if realized["realized_rows"] == 0:
            continue
        proxy_positive = proxy["proxy_shadow_trade_count"] > 0
        realized_negative = realized["mean_realized_net_pnl"] is not None and realized["mean_realized_net_pnl"] < 0
        directional_match = proxy_positive and not realized_negative
        corpus_proxy_positive_count += int(proxy_positive)
        corpus_proxy_positive_realized_negative_count += int(proxy_positive and realized_negative)
        pairs.append(
            {
                "symbol": symbol,
                "scenario": scenario,
                "proxy": proxy,
                "realized": realized,
                "lead_time": {
                    "proxy_observable_before_realized": bool(proxy["earlier_observability_gain"]),
                    "realized_rows_available": realized["realized_rows"],
                },
                "agreement": {
                    "directional_agreement": directional_match,
                    "rank_agreement": False,
                    "false_optimism": bool(proxy_positive and realized_negative),
                },
            }
        )

    false_optimism_count = sum(1 for p in pairs if p["agreement"]["false_optimism"])
    directional_agreement_count = sum(1 for p in pairs if p["agreement"]["directional_agreement"])
    observed_pairs = len(pairs)
    if observed_pairs == 0:
        final_classification = "INSUFFICIENT_OVERLAP"
    elif false_optimism_count > 0 and directional_agreement_count == 0:
        final_classification = "MISLEADING_PROXY"
    elif directional_agreement_count > 0 and false_optimism_count == 0:
        final_classification = "STRONG_DIRECTIONAL_AGREEMENT"
    elif directional_agreement_count > 0:
        final_classification = "WEAK_BUT_USEFUL_AGREEMENT"
    else:
        final_classification = "NOISY_PROXY_WITH_LIMITED_SIGNAL"

    return {
        "metadata": {
            "stamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
            "classification": final_classification,
            "method_version": "proxy_shadow_realized_agreement_v1",
            "shadow_source": str(shadow_path),
            "db_sources": [str(p) for p in db_paths],
        },
        "agreement_pairs": pairs,
        "agreement_metrics": {
            "observed_pairs": observed_pairs,
            "directional_agreement_count": directional_agreement_count,
            "false_optimism_count": false_optimism_count,
            "corpus_proxy_positive_count": corpus_proxy_positive_count,
            "corpus_proxy_positive_realized_negative_count": corpus_proxy_positive_realized_negative_count,
            "mean_proxy_readiness_lead": (
                sum(1.0 for p in pairs if p["lead_time"]["proxy_observable_before_realized"]) / observed_pairs
                if observed_pairs
                else 0.0
            ),
        },
        "false_optimism_definition": {
            "pair_level_rule": "proxy_shadow_trade_count > 0 AND mean_realized_net_pnl < 0 within the matched pair",
            "corpus_level_note": "The shadow corpus can be proxy-positive even when matched realized pairs are not proxy-positive; the pair-level counter does not count unmatched shadow-only rows.",
            "count_scope": "matched realized pairs only",
            "not_counted": [
                "shadow corpus rows that do not have a matched realized pair in the audit set",
                "shadow-positive rows whose realized counterpart is absent from the collected DBs",
            ],
        },
        "why_count_zero": (
            "The matched realized pairs in this audit do not satisfy proxy-positive AND realized-negative simultaneously. "
            "The shadow corpus itself can still be proxy-positive, but those rows are not part of the pair-level false_optimism_count."
        ),
        "lead_time_findings": {
            "proxy_before_realized": sum(1 for p in pairs if p["lead_time"]["proxy_observable_before_realized"]),
            "realized_late": sum(1 for p in pairs if p["realized"]["realized_rows"] > 0),
        },
        "mismatch_categories": {
            "strong_directional_agreement": final_classification == "STRONG_DIRECTIONAL_AGREEMENT",
            "weak_but_useful_agreement": final_classification == "WEAK_BUT_USEFUL_AGREEMENT",
            "noisy_proxy_with_limited_signal": final_classification == "NOISY_PROXY_WITH_LIMITED_SIGNAL",
            "misleading_proxy": final_classification == "MISLEADING_PROXY",
            "insufficient_overlap": final_classification == "INSUFFICIENT_OVERLAP",
        },
        "scope_clarification": {
            "pair_level_false_optimism": "matched-pair only; counts only proxy-positive AND realized-negative within the same symbol/scenario pair",
            "corpus_level_proxy_positivity": "shadow-only rows may be positive outside matched realized pairs",
        },
        "risk_review": {
            "false_positive_risk": "high" if false_optimism_count else "medium",
            "false_confidence_risk": "high" if false_optimism_count else "medium",
            "operator_confusion_risk": "medium_to_high",
            "runtime_misuse_risk": "high",
        },
        "final_classification": final_classification,
    }


def _render_md(report: dict) -> str:
    meta = report["metadata"]
    lines = []
    lines.append("## A. Executive Summary")
    lines.append(
        "The shadow proxy provides earlier observability, but in the matched realized samples it does not show a reliable directional agreement with later realized edge. "
        "Where the realized path exists, the proxy is positive while realized net PnL is negative, so the shadow signal is not safe to interpret as a production-quality predictive signal."
    )
    lines.append("")
    lines.append("## B. Scope")
    lines.append("- Shadow-only proxy readiness vs later realized edge-history")
    lines.append("- PAPER / research only")
    lines.append("- No runtime changes")
    lines.append("")
    lines.append("## C. Files Changed")
    lines.append("- `scripts/proxy_shadow_realized_agreement_audit.py`")
    lines.append("- `tests/test_proxy_shadow_realized_agreement_audit.py`")
    lines.append("")
    lines.append("## D. Matching Method")
    lines.append("Matched shadow and realized outcomes by symbol/scenario pocket source.")
    lines.append("Proxy signal was treated as research-only readiness, not as realized history.")
    lines.append("")
    lines.append("## E. Agreement Metrics")
    lines.append(f"- observed pairs: {report['agreement_metrics']['observed_pairs']}")
    lines.append(f"- directional agreement count: {report['agreement_metrics']['directional_agreement_count']}")
    lines.append(f"- false optimism count: {report['agreement_metrics']['false_optimism_count']}")
    lines.append(f"- corpus proxy-positive count: {report['agreement_metrics']['corpus_proxy_positive_count']}")
    lines.append(
        f"- corpus proxy-positive & realized-negative count: {report['agreement_metrics']['corpus_proxy_positive_realized_negative_count']}"
    )
    lines.append("")
    lines.append("False Optimism Definition")
    lines.append(report["false_optimism_definition"]["pair_level_rule"])
    lines.append(report["false_optimism_definition"]["corpus_level_note"])
    lines.append("")
    lines.append(f"Why count = {report['agreement_metrics']['false_optimism_count']}")
    lines.append(report["why_count_zero"])
    lines.append("")
    lines.append("## F. Lead-Time Findings")
    lines.append(
        "Shadow readiness appears earlier than realized readiness, but that lead time is not enough to justify runtime use by itself."
    )
    lines.append("")
    lines.append("## G. Mismatch Categories")
    lines.append(f"- final classification: {meta['classification']}")
    lines.append("- proxy positive + realized negative is treated as false optimism")
    lines.append("")
    lines.append("## H. Risk Review")
    for k, v in report["risk_review"].items():
        lines.append(f"- {k.replace('_', ' ')}: {v}")
    lines.append("")
    lines.append("## I. Final Classification")
    lines.append(meta["classification"])
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit agreement between shadow proxy readiness and later realized edge.")
    parser.add_argument("--shadow", default=str(DEFAULT_SHADOW))
    parser.add_argument("--db", action="append", dest="db_paths")
    args = parser.parse_args(argv)
    db_paths = [Path(p) for p in args.db_paths] if args.db_paths else DEFAULT_DB_PATHS
    report = _build_report(Path(args.shadow), db_paths)
    stamp = report["metadata"]["stamp"]
    json_path = DIAG_DIR / f"proxy_shadow_realized_agreement_audit_{stamp}.json"
    md_path = DIAG_DIR / f"proxy_shadow_realized_agreement_audit_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
