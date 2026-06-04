from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


WORKDIR = Path(__file__).resolve().parents[1]

CLASS_REALIZED_LOSS_DOMINANT = "FLOW_AUTOPSY_REALIZED_LOSS_DOMINANT"
CLASS_ENTRY_BLOCKED = "FLOW_AUTOPSY_ENTRY_BLOCKED"
CLASS_RISK_BLOCKED = "FLOW_AUTOPSY_RISK_BLOCKED"
CLASS_EXIT_LOSS_DOMINANT = "FLOW_AUTOPSY_EXIT_LOSS_DOMINANT"
CLASS_TELEMETRY_GAP = "FLOW_AUTOPSY_TELEMETRY_GAP"
CLASS_CONTAMINATED = "FLOW_AUTOPSY_EVIDENCE_CONTAMINATED"
CLASS_INCONCLUSIVE = "FLOW_AUTOPSY_INCONCLUSIVE"

CONTAMINATION_KEYS = ("seed", "fallback", "mock", "force_open", "forced_cycle")
RISK_BLOCK_REASONS = {"entry_min_net_guard", "min_size", "net_target_guard"}
ENTRY_BLOCK_REASONS = {
    "entry_edge_filtered",
    "symbol_strategy_side_allowlist",
    "no_runtime_profile",
    "side_expectancy",
}


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _canonical_strategy(value: Any) -> str:
    text = str(value or "").strip().upper().replace("_", "").replace("-", "")
    if text.endswith("V2"):
        text = text[:-2]
    return text


def _is_contaminated(payload: dict[str, Any]) -> bool:
    flags = payload.get("contamination_flags")
    if not isinstance(flags, dict):
        meta = payload.get("meta")
        if isinstance(meta, dict):
            flags = meta.get("contamination_flags")
    if not isinstance(flags, dict):
        return False
    for key in CONTAMINATION_KEYS:
        value = flags.get(key, 0)
        if value is True:
            return True
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value != 0:
            return True
        if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False


def _load_log_payloads(db_path: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    try:
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "logs" not in tables:
            return []
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(logs)")}
        event_col = "event" if "event" in columns else "event_type" if "event_type" in columns else None
        details_col = "details" if "details" in columns else "payload" if "payload" in columns else None
        timestamp_col = "timestamp" if "timestamp" in columns else "ts" if "ts" in columns else None
        if event_col is None or details_col is None:
            return []
        selected = [event_col, details_col]
        if timestamp_col:
            selected.append(timestamp_col)
        rows: list[dict[str, Any]] = []
        for row in conn.execute(f"SELECT {', '.join(selected)} FROM logs ORDER BY rowid ASC"):
            values = dict(zip(selected, row))
            try:
                payload = json.loads(str(values.get(details_col) or "{}"))
            except json.JSONDecodeError:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            payload["event"] = values.get(event_col)
            payload["db_path"] = str(db_path)
            if timestamp_col:
                payload["db_timestamp"] = values.get(timestamp_col)
            rows.append(payload)
        return rows
    finally:
        conn.close()


def _reason_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for row in rows:
        reason = str(
            row.get("reason_code")
            or row.get("local_gate_reason")
            or row.get("effective_gate_reason")
            or "unknown"
        )
        counts[reason] += 1
    return dict(counts.most_common())


def _event_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(row.get("event") or "unknown") for row in rows).most_common())


def _candidate_key(payload: dict[str, Any]) -> str:
    symbol = str(payload.get("symbol") or "").upper()
    strategy = _canonical_strategy(payload.get("canonical_strategy") or payload.get("strategy"))
    side = str(payload.get("side") or "").lower()
    if not symbol or not strategy or side not in {"buy", "sell"}:
        return ""
    return f"{symbol}:{strategy}:{side}"


def _risk_trace(payload: dict[str, Any]) -> dict[str, Any]:
    risk_fields = payload.get("risk_block_fields") if isinstance(payload.get("risk_block_fields"), dict) else {}
    sizing = risk_fields.get("sizing_trace") if isinstance(risk_fields.get("sizing_trace"), dict) else {}
    cost = payload.get("cost_breakdown") if isinstance(payload.get("cost_breakdown"), dict) else {}
    return {
        "symbol": payload.get("symbol"),
        "strategy": payload.get("strategy"),
        "side": payload.get("side"),
        "reason_code": payload.get("reason_code"),
        "expected_net_after_cost": payload.get("expected_net_after_cost"),
        "expected_net_after_full_cost": sizing.get("expected_net_after_full_cost"),
        "final_notional_usdt": sizing.get("final_notional_usdt"),
        "entry_min_net_usdt": sizing.get("entry_min_net_usdt"),
        "runtime_profile_source": cost.get("runtime_profile_source"),
    }


def _normalize_close(payload: dict[str, Any]) -> dict[str, Any]:
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    sizing = meta.get("sizing_trace") if isinstance(meta.get("sizing_trace"), dict) else {}
    cost = meta.get("cost_breakdown") if isinstance(meta.get("cost_breakdown"), dict) else {}
    symbol = str(payload.get("symbol") or "").upper()
    strategy = _canonical_strategy(payload.get("strategy"))
    side = str(payload.get("side") or "").lower()
    return {
        "candidate_key": f"{symbol}:{strategy}:{side}",
        "symbol": symbol,
        "canonical_strategy": strategy,
        "side": side,
        "realized_pnl": _safe_float(payload.get("realized_pnl")),
        "realized_gross": _safe_float(payload.get("realized_gross")),
        "notional_usdt": _safe_float(payload.get("notional_usdt")),
        "entry_fee_usdt": _safe_float(payload.get("entry_fee_usdt")),
        "exit_fee_usdt": _safe_float(payload.get("exit_fee_usdt")),
        "exit_reason": payload.get("exit_reason") or payload.get("close_reason") or "unknown",
        "expected_net_after_full_cost": _safe_float(
            sizing.get("expected_net_after_full_cost") or meta.get("expected_net_after_full_cost")
        ),
        "final_notional_usdt": _safe_float(sizing.get("final_notional_usdt")),
        "runtime_profile_source": cost.get("runtime_profile_source"),
        "expected_move_raw": _safe_float(cost.get("expected_move_raw")),
        "expected_move_scaled": _safe_float(cost.get("expected_move_scaled")),
        "contaminated": _is_contaminated(payload),
        "db_path": payload.get("db_path"),
    }


def _bucket_summaries(closes: list[dict[str, Any]], min_trades: int) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in closes:
        buckets[row["candidate_key"]].append(row)
    summaries = []
    for key, rows in buckets.items():
        pnls = [row["realized_pnl"] for row in rows]
        wins = [pnl for pnl in pnls if pnl > 0]
        losses = [abs(pnl) for pnl in pnls if pnl <= 0]
        gross_win = sum(wins)
        gross_loss = sum(losses)
        win_rate = len(wins) / len(pnls) if pnls else 0.0
        profit_factor = gross_win / gross_loss if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)
        summaries.append(
            {
                "candidate_key": key,
                "trade_count": len(pnls),
                "win_count": len(wins),
                "loss_count": len(losses),
                "win_rate": win_rate,
                "net_pnl": sum(pnls),
                "avg_win": mean(wins) if wins else 0.0,
                "avg_loss_abs": mean(losses) if losses else 0.0,
                "profit_factor": profit_factor,
                "avg_expected_net_after_full_cost": mean([row["expected_net_after_full_cost"] for row in rows]),
                "exit_reason_counts": dict(Counter(row["exit_reason"] for row in rows).most_common()),
                "passes_realized_target": (
                    len(pnls) >= min_trades and sum(pnls) > 0.0 and win_rate >= 0.55 and profit_factor >= 1.20
                ),
            }
        )
    summaries.sort(key=lambda item: (item["passes_realized_target"], item["net_pnl"], item["profit_factor"]), reverse=True)
    return summaries


def _exit_flow(closes: list[dict[str, Any]]) -> dict[str, Any]:
    by_reason: dict[str, list[float]] = defaultdict(list)
    for row in closes:
        by_reason[str(row["exit_reason"])].append(float(row["realized_pnl"]))
    pnl = {reason: sum(values) for reason, values in by_reason.items()}
    counts = {reason: len(values) for reason, values in by_reason.items()}
    negative = {reason: value for reason, value in pnl.items() if value < 0}
    dominant = min(negative.items(), key=lambda item: item[1])[0] if negative else None
    return {
        "exit_reason_counts": dict(sorted(counts.items())),
        "exit_reason_pnl": dict(sorted(pnl.items())),
        "dominant_loss_exit_reason": dominant,
        "protective_exit_loss_pnl": pnl.get("protective_exit", 0.0),
        "time_decay_exit_pnl": pnl.get("time_decay_exit", 0.0),
        "run_end_pnl": pnl.get("run_end", 0.0),
    }


def _result_env_provenance(result_paths: list[Path]) -> dict[str, Any]:
    keys = (
        "LIVE",
        "USE_MOCK",
        "ENTRY_MIN_NET_USDT",
        "RUNTIME_V2_POST_SIGNAL_TRAJECTORY",
        "SEED_TRADES_ENABLE",
        "DIAGNOSTIC_FORCE_OPEN",
        "PAPER_AUTO_OPEN_FALLBACK_ENABLE",
        "PAPER_AUTO_OPEN_REQUIRE_EXPLICIT_SIDE_ALLOWLIST",
    )
    runs = []
    invalid = []
    for path in result_paths:
        if not path.exists():
            invalid.append({"path": str(path), "reason": "missing_result_json"})
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            invalid.append({"path": str(path), "reason": "invalid_json"})
            continue
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        after = data.get("after") if isinstance(data.get("after"), dict) else {}
        env = {}
        for source in (
            params.get("after_env_overrides_cli"),
            params.get("after_env_overrides"),
            after.get("effective_env_values"),
            after.get("diagnostic_env_flags"),
        ):
            if isinstance(source, dict):
                for key in keys:
                    if key in source and key not in env:
                        env[key] = source[key]
        admission = data.get("entry_admission_contract") if isinstance(data.get("entry_admission_contract"), dict) else {}
        fail_closed = False
        reasons: list[str] = []
        if admission and (
            str(admission.get("status") or "").upper() != "PASS"
            or not bool(admission.get("profit_valid", data.get("profit_valid", True)))
            or bool(data.get("invalid_reason"))
            or bool(admission.get("invalid_reason"))
        ):
            fail_closed = True
            reasons.append(
                str(admission.get("invalid_reason") or data.get("invalid_reason") or admission.get("status") or "invalid_admission_contract")
            )
        run = {"path": str(path), "env": env, "fail_closed": fail_closed, "reasons": reasons}
        runs.append(run)
        if fail_closed:
            invalid.append({"path": str(path), "reason": ",".join(reasons)})
    return {"runs": runs, "invalid_evidence": invalid}


def _classify(
    *,
    contaminated_count: int,
    gaps: list[str],
    position_open_count: int,
    position_close_count: int,
    risk_block_counts: dict[str, int],
    entry_block_counts: dict[str, int],
    realized_net_pnl: float,
    passing_bucket_count: int,
    dominant_loss_exit_reason: str | None,
) -> str:
    if contaminated_count:
        return CLASS_CONTAMINATED
    if gaps:
        return CLASS_TELEMETRY_GAP
    if position_close_count > 0 and passing_bucket_count == 0 and dominant_loss_exit_reason == "protective_exit":
        return CLASS_EXIT_LOSS_DOMINANT
    if position_close_count > 0 and realized_net_pnl < 0:
        return CLASS_REALIZED_LOSS_DOMINANT
    if position_open_count == 0 and any(count > 0 for count in risk_block_counts.values()):
        return CLASS_RISK_BLOCKED
    if position_open_count == 0 and any(count > 0 for count in entry_block_counts.values()):
        return CLASS_ENTRY_BLOCKED
    return CLASS_INCONCLUSIVE


def audit_runtime_profitability_flow(
    db_paths: list[Path | str],
    result_paths: list[Path | str] | None = None,
    min_realized_trades: int = 5,
) -> dict[str, Any]:
    dbs = [Path(path) for path in db_paths]
    results = [Path(path) for path in (result_paths or [])]
    rows = [payload for db in dbs for payload in _load_log_payloads(db)]
    event_counts = _event_counts(rows)
    entry_eval_rows = [row for row in rows if row.get("event") == "entry_eval_v2"]
    entry_reject_rows = [row for row in rows if row.get("event") == "entry_reject_v2"]
    risk_decision_rows = [row for row in rows if row.get("event") == "risk_decision"]
    gate_summary_rows = [row for row in rows if row.get("event") == "entry_gate_decision_summary"]
    position_open_rows = [row for row in rows if row.get("event") in {"position_open", "position_open_v2"}]
    close_rows_raw = [row for row in rows if row.get("event") == "position_close"]
    closes = [_normalize_close(row) for row in close_rows_raw]
    contaminated_count = sum(1 for row in rows if _is_contaminated(row))
    clean_closes = [row for row in closes if not row["contaminated"]]
    risk_block_rows = [
        row
        for row in entry_reject_rows + risk_decision_rows + gate_summary_rows
        if str(row.get("reason_code") or row.get("local_gate_reason") or "") in RISK_BLOCK_REASONS
    ]
    entry_block_rows = [
        row
        for row in entry_reject_rows + risk_decision_rows + gate_summary_rows
        if str(row.get("reason_code") or row.get("local_gate_reason") or "") in ENTRY_BLOCK_REASONS
    ]
    risk_block_counts = _reason_counts(risk_block_rows)
    entry_block_counts = _reason_counts(entry_block_rows)
    buckets = _bucket_summaries(clean_closes, min_trades=min_realized_trades)
    passing = [row for row in buckets if row["passes_realized_target"]]
    exit_flow = _exit_flow(clean_closes)
    gaps = []
    if entry_eval_rows and not risk_decision_rows:
        gaps.append("risk_decision")
    if risk_decision_rows and position_open_rows and not close_rows_raw:
        gaps.append("position_close")
    if entry_eval_rows and not close_rows_raw and not risk_block_rows and not entry_block_rows:
        gaps.append("position_close")
    realized_net_pnl = sum(row["realized_pnl"] for row in clean_closes)
    inferred_position_open_count = max(len(position_open_rows), len(close_rows_raw))
    if close_rows_raw and not position_open_rows:
        gaps.append("position_open_event_absent_inferred_from_position_close")
    classification = _classify(
        contaminated_count=contaminated_count,
        gaps=[gap for gap in gaps if gap != "position_open_event_absent_inferred_from_position_close"],
        position_open_count=inferred_position_open_count,
        position_close_count=len(close_rows_raw),
        risk_block_counts=risk_block_counts,
        entry_block_counts=entry_block_counts,
        realized_net_pnl=realized_net_pnl,
        passing_bucket_count=len(passing),
        dominant_loss_exit_reason=exit_flow["dominant_loss_exit_reason"],
    )
    entry_eval_allow_count = sum(1 for row in entry_eval_rows if row.get("reason_code") == "allow")
    downstream_unopened_allow_count = max(0, entry_eval_allow_count - len(position_open_rows))
    return {
        "classification": classification,
        "inputs": {
            "db_paths": [str(path) for path in dbs],
            "result_paths": [str(path) for path in results],
        },
        "flow_map": [
            "QuoteTick",
            "FeatureEngine",
            "StrategyStack",
            "DecisionEngineV2",
            "RiskEngineV2",
            "position_open",
            "ExitEngineV2",
            "position_close",
            "realized_history",
        ],
        "event_counts": event_counts,
        "telemetry_gaps": gaps,
        "data_source_flow": {
            "runtime_source_required": "rolling_quote_window",
            "post_signal_event_count": event_counts.get("post_signal_trajectory_v2", 0),
            "runtime_profile_sources_seen": sorted(
                {
                    str((row.get("cost_breakdown") or {}).get("runtime_profile_source"))
                    for row in entry_eval_rows + entry_reject_rows
                    if isinstance(row.get("cost_breakdown"), dict)
                    and (row.get("cost_breakdown") or {}).get("runtime_profile_source")
                }
            ),
        },
        "entry_flow": {
            "entry_eval_count": len(entry_eval_rows),
            "entry_eval_reason_counts": _reason_counts(entry_eval_rows),
            "entry_reject_count": len(entry_reject_rows),
            "entry_reject_reason_counts": _reason_counts(entry_reject_rows),
            "gate_summary_reason_counts": _reason_counts(gate_summary_rows),
            "downstream_unopened_allow_count": downstream_unopened_allow_count,
        },
        "risk_flow": {
            "risk_decision_count": len(risk_decision_rows),
            "risk_decision_reason_counts": _reason_counts(risk_decision_rows),
            "risk_block_reason_counts": risk_block_counts,
            "risk_block_samples": [_risk_trace(row) for row in risk_block_rows[:20]],
        },
        "execution_flow": {
            "position_open_count": inferred_position_open_count,
            "explicit_position_open_event_count": len(position_open_rows),
            "inferred_position_open_count": len(close_rows_raw) if close_rows_raw and not position_open_rows else 0,
            "position_close_count": len(close_rows_raw),
            "open_close_delta": inferred_position_open_count - len(close_rows_raw),
        },
        "exit_flow": exit_flow,
        "realized_flow": {
            "trade_count": len(close_rows_raw),
            "clean_trade_count": len(clean_closes),
            "net_pnl": realized_net_pnl,
            "win_rate": (sum(1 for row in clean_closes if row["realized_pnl"] > 0) / len(clean_closes))
            if clean_closes
            else 0.0,
            "bucket_count": len(buckets),
            "passing_bucket_count": len(passing),
            "bucket_summaries": buckets,
        },
        "history_flow": {
            "write_event": "position_close",
            "position_close_count": len(close_rows_raw),
            "bucket_keys_seen": sorted({row["candidate_key"] for row in clean_closes}),
        },
        "provenance": {
            "contaminated_event_count": contaminated_count,
            "result_env": _result_env_provenance(results) if results else {"runs": [], "invalid_evidence": []},
        },
        "decision": _decision(classification),
        "profitability_claim": False,
    }


def _decision(classification: str) -> dict[str, Any]:
    if classification == CLASS_EXIT_LOSS_DOMINANT:
        return {
            "next_step": "exit_or_quality_redesign_from_realized_losers",
            "patch_runtime_now": False,
            "reason": "natural paper trades exist but protective_exit losses dominate realized PnL",
        }
    if classification == CLASS_REALIZED_LOSS_DOMINANT:
        return {
            "next_step": "do_not_promote_current_profile",
            "patch_runtime_now": False,
            "reason": "natural paper trades exist but realized bucket PnL is negative",
        }
    if classification == CLASS_RISK_BLOCKED:
        return {
            "next_step": "risk_sizing_or_contract_blocker_audit",
            "patch_runtime_now": False,
            "reason": "entry candidates reach allow but downstream risk gates block position open",
        }
    if classification == CLASS_ENTRY_BLOCKED:
        return {
            "next_step": "entry_signal_or_allowlist_blocker_audit",
            "patch_runtime_now": False,
            "reason": "entry layer blocks before risk/order path",
        }
    if classification == CLASS_TELEMETRY_GAP:
        return {
            "next_step": "repair_or_repeat_telemetry_capture",
            "patch_runtime_now": False,
            "reason": "required flow telemetry is missing",
        }
    if classification == CLASS_CONTAMINATED:
        return {
            "next_step": "discard_contaminated_evidence",
            "patch_runtime_now": False,
            "reason": "seed/fallback/mock/force-open contamination present",
        }
    return {
        "next_step": "collect_additional_clean_runtime_evidence",
        "patch_runtime_now": False,
        "reason": "flow evidence is insufficient for a stronger classification",
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Runtime Profitability Flow Autopsy",
        "",
        f"- classification: `{report['classification']}`",
        f"- profitability_claim: `{report['profitability_claim']}`",
        f"- next_step: `{report['decision']['next_step']}`",
        f"- contaminated_event_count: `{report['provenance']['contaminated_event_count']}`",
        f"- telemetry_gaps: `{','.join(report['telemetry_gaps']) or '-'}`",
        "",
        "## Flow Counts",
        f"- entry_eval_v2: `{report['entry_flow']['entry_eval_count']}`",
        f"- entry_reject_v2: `{report['entry_flow']['entry_reject_count']}`",
        f"- risk_decision: `{report['risk_flow']['risk_decision_count']}`",
        f"- position_open: `{report['execution_flow']['position_open_count']}`",
        f"- explicit_position_open_event_count: `{report['execution_flow']['explicit_position_open_event_count']}`",
        f"- inferred_position_open_count: `{report['execution_flow']['inferred_position_open_count']}`",
        f"- position_close: `{report['execution_flow']['position_close_count']}`",
        f"- downstream_unopened_allow_count: `{report['entry_flow']['downstream_unopened_allow_count']}`",
        "",
        "## Risk Blockers",
    ]
    if report["risk_flow"]["risk_block_reason_counts"]:
        for reason, count in report["risk_flow"]["risk_block_reason_counts"].items():
            lines.append(f"- {reason}: `{count}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Exit / Realized"])
    lines.append(f"- net_pnl: `{report['realized_flow']['net_pnl']}`")
    lines.append(f"- win_rate: `{report['realized_flow']['win_rate']}`")
    lines.append(f"- dominant_loss_exit_reason: `{report['exit_flow']['dominant_loss_exit_reason']}`")
    for reason, pnl in report["exit_flow"]["exit_reason_pnl"].items():
        lines.append(f"- {reason}: pnl=`{pnl}` count=`{report['exit_flow']['exit_reason_counts'].get(reason, 0)}`")
    lines.extend(["", "## Bucket Summaries"])
    for row in report["realized_flow"]["bucket_summaries"][:20]:
        lines.append(
            "- `{candidate}` trades=`{trades}` net=`{net}` win_rate=`{win}` pf=`{pf}` pass=`{passes}` exits=`{exits}`".format(
                candidate=row["candidate_key"],
                trades=row["trade_count"],
                net=row["net_pnl"],
                win=row["win_rate"],
                pf=row["profit_factor"],
                passes=row["passes_realized_target"],
                exits=row["exit_reason_counts"],
            )
        )
    lines.extend(["", "## Provenance"])
    for invalid in report["provenance"]["result_env"]["invalid_evidence"]:
        lines.append(f"- invalid_result: `{invalid['path']}` reason=`{invalid['reason']}`")
    if not report["provenance"]["result_env"]["invalid_evidence"]:
        lines.append("- invalid_result: `none`")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", action="append", default=[])
    parser.add_argument("--db-glob", default="")
    parser.add_argument("--result", action="append", default=[])
    parser.add_argument("--result-glob", default="")
    parser.add_argument("--min-realized-trades", type=int, default=5)
    parser.add_argument("--output-json", default="analysis/runtime_profitability_flow_autopsy_current.json")
    parser.add_argument("--output-md", default="analysis/runtime_profitability_flow_autopsy_current.md")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_paths = [Path(path) for path in args.db]
    result_paths = [Path(path) for path in args.result]
    if args.db_glob:
        db_paths.extend(sorted(WORKDIR.glob(args.db_glob)))
    if args.result_glob:
        result_paths.extend(sorted(WORKDIR.glob(args.result_glob)))
    report = audit_runtime_profitability_flow(
        db_paths,
        result_paths=result_paths,
        min_realized_trades=int(args.min_realized_trades),
    )
    output_json = WORKDIR / args.output_json
    output_md = WORKDIR / args.output_md
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    output_md.write_text(render_markdown(report), encoding="utf-8")
    print(report["classification"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
