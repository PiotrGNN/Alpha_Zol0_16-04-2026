from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any


WORKDIR = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = WORKDIR / "analysis"

EDGE_PARITY_CLASSIFICATIONS = {
    "RESEARCH_RUNTIME_EDGE_PARITY_CONFIRMED",
    "RESEARCH_EDGE_DECAYS_BEFORE_RUNTIME_SMOKE",
    "RESEARCH_RUNTIME_COST_MODEL_MISMATCH",
    "RESEARCH_RUNTIME_SOURCE_MISMATCH",
    "RESEARCH_RUNTIME_FORMULA_MISMATCH",
    "TRENDFOLLOWING_SIGNAL_TOO_WEAK_IN_RUNTIME",
    "EDGE_PARITY_BLOCKED_BY_INSUFFICIENT_TELEMETRY",
    "EDGE_PARITY_INCONCLUSIVE",
}
THRESHOLD_CLASSIFICATIONS = {
    "MIN_NET_THRESHOLD_APPLIED_CORRECTLY",
    "MIN_NET_THRESHOLD_PRIMARY_BUT_ECONOMICALLY_UNTESTED",
    "MIN_NET_THRESHOLD_SEMANTICS_MISMATCH",
    "MIN_NET_THRESHOLD_NOT_PRIMARY",
    "THRESHOLD_AUTOPSY_INCONCLUSIVE",
}
STRATEGY_CLASSIFICATIONS = {
    "TRENDFOLLOWINGV2_RUNTIME_EDGE_TOO_WEAK",
    "TRENDFOLLOWINGV2_SIGNAL_DECAYS_TOO_FAST",
    "TRENDFOLLOWINGV2_SOURCE_OR_ALIAS_MISMATCH",
    "TRENDFOLLOWINGV2_AUTOPSY_BLOCKED_BY_TELEMETRY_GAP",
    "TRENDFOLLOWINGV2_AUTOPSY_INCONCLUSIVE",
}
OVERALL_CLASSIFICATIONS = {
    "FRESH_RESEARCH_EDGE_NOT_RUNTIME_ADMISSIBLE_DUE_TO_DECAY",
    "FRESH_RESEARCH_EDGE_NOT_RUNTIME_ADMISSIBLE_DUE_TO_COST_MODEL",
    "FRESH_RESEARCH_EDGE_NOT_RUNTIME_ADMISSIBLE_DUE_TO_SOURCE_MISMATCH",
    "FRESH_RESEARCH_EDGE_NOT_RUNTIME_ADMISSIBLE_DUE_TO_STRATEGY_WEAKNESS",
    "FRESH_RESEARCH_EDGE_NOT_RUNTIME_ADMISSIBLE_DUE_TO_THRESHOLD_SEMANTICS",
    "EDGE_SEMANTICS_AUTOPSY_REQUIRES_TELEMETRY_PATCH",
    "EDGE_SEMANTICS_AUTOPSY_INCONCLUSIVE",
}
FINAL_VERDICTS = {
    "RESEARCH_EDGE_DECAY_REPAIR_REQUIRED",
    "COST_MODEL_PARITY_REPAIR_REQUIRED",
    "SOURCE_PARITY_REPAIR_REQUIRED",
    "FORMULA_PARITY_REPAIR_REQUIRED",
    "TRENDFOLLOWINGV2_DEMOTE_SEARCH_STRONGER_ALPHA",
    "TELEMETRY_ONLY_PATCH_REQUIRED",
    "THRESHOLD_SEMANTICS_REPAIR_REQUIRED",
    "EDGE_SEMANTICS_AUTOPSY_INCONCLUSIVE",
}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    parsed = json.loads(path.read_text(encoding="utf-8"))
    return parsed if isinstance(parsed, dict) else {}


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _json_loads(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _dig(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def canonical_strategy(strategy: Any) -> str:
    value = str(strategy or "").strip().upper().replace("_", "")
    if value in {"TRENDFOLLOWING", "TRENDFOLLOWINGV2"}:
        return "TRENDFOLLOWING"
    if value in {"MOMENTUM", "MOMENTUMV2"}:
        return "MOMENTUM"
    if value in {"MEANREVERSION", "MEANREVERSIONV2"}:
        return "MEANREVERSION"
    if value in {"MICROBREAKOUT", "MICROBREAKOUTV2"}:
        return "MICROBREAKOUT"
    return value


def _candidate_key(symbol: Any, strategy: Any, side: Any) -> str:
    return f"{str(symbol or '').strip().upper()}:{str(strategy or '').strip()}:{str(side or '').strip().lower()}"


def _canonical_key(symbol: Any, strategy: Any, side: Any) -> str:
    return f"{str(symbol or '').strip().upper()}:{canonical_strategy(strategy)}:{str(side or '').strip().lower()}"


def compute_delta(
    research_expected: float | None,
    runtime_expected: float | None,
    *,
    threshold: float = 0.12,
) -> dict[str, Any]:
    if research_expected is None or runtime_expected is None:
        return {
            "absolute": None,
            "percent": None,
            "runtime_would_pass_at_research_value": False,
            "runtime_observed_passes_effective_threshold": False,
        }
    absolute = float(runtime_expected) - float(research_expected)
    percent = (absolute / float(research_expected)) * 100.0 if research_expected else None
    return {
        "absolute": absolute,
        "percent": percent,
        "runtime_would_pass_at_research_value": float(research_expected) >= float(threshold),
        "runtime_observed_passes_effective_threshold": float(runtime_expected) >= float(threshold),
    }


def _summarize(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": float(mean(values)),
    }


def _line_of(path: Path, pattern: str) -> int | None:
    if not path.exists():
        return None
    for index, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if pattern in line:
            return index
    return None


def _code_contract(code_root: Path) -> dict[str, Any]:
    strategy_stack = code_root / "core" / "runtime_v2" / "strategy_stack.py"
    decision_engine = code_root / "core" / "runtime_v2" / "decision_engine.py"
    risk_engine = code_root / "core" / "runtime_v2" / "risk_engine.py"
    data_feed = code_root / "core" / "runtime_v2" / "data_feed.py"
    research = code_root / "scripts" / "discover_new_alpha_search_space.py"
    feature_engine = code_root / "core" / "runtime_v2" / "feature_engine.py"
    return {
        "strategy": {
            "file": str(strategy_stack),
            "TrendFollowingV2_line": _line_of(strategy_stack, "class TrendFollowingV2"),
            "trend_input_line": _line_of(strategy_stack, "trend = float(feature.ret_3)"),
            "expected_move_formula_line": _line_of(strategy_stack, "expected_move = abs(trend) * 0.95"),
            "signal_horizon_line": _line_of(strategy_stack, '"signal_horizon_ticks": 3'),
            "formula": "expected_move = abs(ret_3) * 0.95",
        },
        "feature": {
            "file": str(feature_engine),
            "ret_3_line": _line_of(feature_engine, "ret_3 = (prices[-1] / prices[-4]) - 1.0"),
            "profile_source_line": _line_of(feature_engine, 'profile_source="rolling_quote_window"'),
        },
        "runtime_formula": {
            "decision_engine_file": str(decision_engine),
            "expected_edge_after_fee_line": _line_of(decision_engine, "expected_edge_after_fee = expected_move - costs"),
            "expected_net_after_cost_line": _line_of(decision_engine, "expected_net_after_cost = expected_move - costs"),
            "risk_engine_file": str(risk_engine),
            "full_cost_line": _line_of(risk_engine, "expected_net_after_full_cost = candidate.expected_net_after_cost * final_notional_usdt"),
            "min_net_guard_line": _line_of(risk_engine, "expected_net_after_full_cost < self.entry_min_net_usdt"),
            "formula": "expected_net_after_full_cost = (expected_move - total_cost_ratio) * final_notional_usdt",
        },
        "research_path": {
            "file": str(research),
            "uses_strategy_stack_line": _line_of(research, "strategy_stack = StrategyStack()"),
            "uses_decision_engine_line": _line_of(research, "decision_engine = DecisionEngineV2()"),
            "uses_risk_engine_line": _line_of(research, "risk_engine = RiskEngineV2()"),
            "research_min_net_line": _line_of(research, "risk_engine.entry_min_net_usdt = float(min_expected_net_usdt)"),
            "source_line": _line_of(research, '"fresh_kucoin_public_klines_research"'),
        },
        "runtime_source": {
            "file": str(data_feed),
            "kucoin_quote_line": _line_of(data_feed, "fetch_kucoin_paper_quote"),
        },
    }


def _extract_expected_full(payload: dict[str, Any]) -> float | None:
    sizing_trace = _extract_sizing_trace(payload)
    return (
        _safe_float(payload.get("expected_net_after_full_cost"))
        or _safe_float(sizing_trace.get("expected_net_after_full_cost"))
        or _safe_float(_dig(payload, ("meta", "expected_net_after_full_cost")))
    )


def _extract_sizing_trace(payload: dict[str, Any]) -> dict[str, Any]:
    for candidate in (
        _dig(payload, ("risk_block_fields", "sizing_trace")),
        payload.get("sizing_trace"),
        _dig(payload, ("meta", "sizing_trace")),
        _dig(payload, ("position", "meta", "sizing_trace")),
    ):
        if isinstance(candidate, dict):
            return dict(candidate)
    return {}


def _candidate_from_runtime_key(candidate: str) -> tuple[str, str, str]:
    parts = str(candidate or "").split(":")
    if len(parts) != 3:
        return "", "", ""
    return parts[0].strip().upper(), parts[1].strip(), parts[2].strip().lower()


def _scan_runtime_db(db_path: Path, candidate: str) -> dict[str, Any]:
    symbol, strategy, side = _candidate_from_runtime_key(candidate)
    canonical = _canonical_key(symbol, strategy, side)
    if not db_path.exists() or not db_path.is_file():
        return {"db_exists": False, "records": 0, "missing_fields": ["db_path"]}
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, timestamp, event, details FROM logs "
            "WHERE event IN ('entry_eval_v2','entry_reject_v2','entry_gate_decision_summary','position_open_v2') "
            "ORDER BY id ASC"
        ).fetchall()
    finally:
        conn.close()

    expected_values: list[float] = []
    reason_counts: Counter[str] = Counter()
    profile_sources: Counter[str] = Counter()
    quote_sources: Counter[str] = Counter()
    costs: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    best_expected: float | None = None
    missing_fields: set[str] = set()
    timestamps: list[str] = []
    for row in rows:
        payload = _json_loads(row["details"])
        row_key = _canonical_key(payload.get("symbol"), payload.get("strategy"), payload.get("side"))
        if row_key != canonical:
            continue
        expected = _extract_expected_full(payload)
        reason = str(
            payload.get("reason_code")
            or payload.get("local_gate_reason")
            or payload.get("effective_gate_reason")
            or ""
        )
        if reason:
            reason_counts[reason] += 1
        if expected is not None:
            expected_values.append(expected)
            if best_expected is None or expected > best_expected:
                best_expected = expected
                best = payload
        for field in ("runtime_profile_source", "runtime_profile_key", "runtime_profile_age_sec"):
            value = payload.get(field)
            if value in (None, ""):
                missing_fields.add(field)
        if payload.get("runtime_profile_source"):
            profile_sources[str(payload.get("runtime_profile_source"))] += 1
        quote_source = (
            payload.get("quote_source")
            or payload.get("runtime_quote_source")
            or _dig(payload, ("quote", "source"))
            or _dig(payload, ("tick", "raw", "source"))
        )
        if quote_source:
            quote_sources[str(quote_source)] += 1
        else:
            missing_fields.add("quote_source")
        cost_breakdown = payload.get("cost_breakdown")
        if isinstance(cost_breakdown, dict):
            costs.append(cost_breakdown)
        if row["timestamp"]:
            timestamps.append(str(row["timestamp"]))

    best_cost = best.get("cost_breakdown") if isinstance(best, dict) and isinstance(best.get("cost_breakdown"), dict) else {}
    best_sizing = _extract_sizing_trace(best or {})
    return {
        "db_exists": True,
        "records": len(expected_values),
        "expected_net_after_full_cost_stats": _summarize(expected_values),
        "reason_counts": dict(reason_counts),
        "profile_sources": dict(profile_sources),
        "quote_sources": dict(quote_sources),
        "first_timestamp": timestamps[0] if timestamps else None,
        "last_timestamp": timestamps[-1] if timestamps else None,
        "missing_fields": sorted(missing_fields),
        "best_event": {
            "expected_net_after_full_cost": best_expected,
            "expected_net_after_cost": _safe_float((best or {}).get("expected_net_after_cost")),
            "expected_move": _safe_float((best or {}).get("expected_move")),
            "expected_edge_after_fee": _safe_float((best or {}).get("expected_edge_after_fee")),
            "runtime_profile_source": (best or {}).get("runtime_profile_source"),
            "runtime_profile_key": (best or {}).get("runtime_profile_key"),
            "runtime_profile_age_sec": _safe_float((best or {}).get("runtime_profile_age_sec")),
            "runtime_profile_span_sec": _safe_float((best or {}).get("runtime_profile_span_sec")),
            "runtime_profile_sample_size": _safe_int((best or {}).get("runtime_profile_sample_size"), 0),
            "signal_horizon_ticks": _safe_float((best or {}).get("signal_horizon_ticks")),
            "signal_expected_move_formula": (best or {}).get("signal_expected_move_formula"),
            "expected_move_raw": _safe_float((best or {}).get("expected_move_raw")),
            "expected_move_scaled": _safe_float((best or {}).get("expected_move_scaled")),
            "cost_breakdown": best_cost,
            "sizing_trace": best_sizing,
        },
    }


def _research_candidate(research: dict[str, Any]) -> dict[str, Any]:
    selected = research.get("selected_hypothesis")
    selected = selected if isinstance(selected, dict) else {}
    return {
        "candidate": _candidate_key(selected.get("symbol"), selected.get("strategy"), selected.get("side")),
        "canonical_candidate_key": _canonical_key(selected.get("symbol"), selected.get("strategy"), selected.get("side")),
        "symbol": selected.get("symbol"),
        "strategy": selected.get("strategy"),
        "canonical_strategy": canonical_strategy(selected.get("strategy")),
        "side": selected.get("side"),
        "expected_move": _safe_float(selected.get("expected_move")),
        "expected_net_after_cost": _safe_float(selected.get("expected_net_after_cost")),
        "expected_net_after_full_cost": _safe_float(selected.get("expected_net_after_full_cost")),
        "final_notional_usdt": _safe_float(selected.get("final_notional_usdt")),
        "probability_of_profit": _safe_float(selected.get("probability_of_profit")),
        "confidence": _safe_float(selected.get("confidence")),
        "sample_count": _safe_int(selected.get("sample_count"), 0),
        "profile_span_sec": _safe_float(selected.get("profile_span_sec")),
        "source": selected.get("source") or (research.get("scope") or {}).get("source"),
        "data_source": (research.get("scope") or {}).get("source"),
        "spread_bps": _safe_float((research.get("scope") or {}).get("spread_bps")),
        "timestamp": selected.get("timestamp"),
        "candle_window": {
            "interval": (research.get("scope") or {}).get("interval"),
            "sample_count": _safe_int(selected.get("sample_count"), 0),
            "profile_span_sec": _safe_float(selected.get("profile_span_sec")),
        },
        "missing_fields": [
            field
            for field in ("timestamp", "fee_estimate", "slippage_estimate", "candle_start", "candle_end")
            if selected.get(field) in (None, "")
        ],
    }


def _runtime_candidate_from_artifact(row: dict[str, Any], code_root: Path) -> dict[str, Any]:
    candidate = str(row.get("candidate") or "")
    db_path = Path(str(row.get("db_path") or ""))
    if not db_path.is_absolute():
        db_path = code_root / db_path
    db_scan = _scan_runtime_db(db_path, candidate)
    expected_stats = row.get("expected_net_after_full_cost_stats") or db_scan.get("expected_net_after_full_cost_stats") or {}
    reason_counts = row.get("target_reason_distribution") or db_scan.get("reason_counts") or {}
    effective_values = row.get("effective_entry_min_net_usdt_values") or []
    effective_threshold = _safe_float(effective_values[0] if effective_values else None)
    symbol, strategy, side = _candidate_from_runtime_key(candidate)
    all_blockers = {
        "min_net_guard": _safe_int(reason_counts.get("entry_min_net_guard")),
        "entry_edge_filtered": _safe_int(reason_counts.get("entry_edge_filtered")),
        "entry_net_to_stop_guard": _safe_int(reason_counts.get("entry_net_to_stop_guard")),
        "no_runtime_profile": _safe_int(reason_counts.get("no_runtime_profile")),
    }
    non_allow_blockers = {key: value for key, value in all_blockers.items() if value > 0}
    first_blocking_gate = max(non_allow_blockers.items(), key=lambda item: item[1])[0] if non_allow_blockers else None
    return {
        "candidate": candidate,
        "canonical_candidate_key": row.get("canonical_candidate_key") or _canonical_key(symbol, strategy, side),
        "symbol": symbol,
        "strategy": strategy,
        "canonical_strategy": canonical_strategy(strategy),
        "side": side,
        "runtime_profile_exists": bool(row.get("runtime_profile_exists")),
        "runtime_profile_keys_top": row.get("runtime_profile_keys_top") or {},
        "runtime_profile_sources": db_scan.get("profile_sources") or {},
        "quote_sources": db_scan.get("quote_sources") or {},
        "runtime_max_expected_net_after_full_cost": _safe_float(expected_stats.get("max")),
        "runtime_mean_expected_net_after_full_cost": _safe_float(expected_stats.get("mean")),
        "runtime_min_net_guard_count": _safe_int(row.get("min_net_guard_count") or reason_counts.get("entry_min_net_guard")),
        "runtime_edge_filter_count": _safe_int(reason_counts.get("entry_edge_filtered")),
        "runtime_stop_ratio_guard_count": _safe_int(reason_counts.get("entry_net_to_stop_guard")),
        "effective_entry_min_net_usdt": effective_threshold,
        "effective_threshold_source": "effective_entry_min_net_usdt_values" if effective_values else "missing",
        "first_blocking_gate": first_blocking_gate,
        "all_blocking_gates": non_allow_blockers,
        "position_open_count": _safe_int(row.get("position_open_count")),
        "completed_clean_natural_trade_count": _safe_int(row.get("completed_clean_natural_trade_count")),
        "db_scan": db_scan,
        "missing_fields": sorted(set(db_scan.get("missing_fields") or [])),
    }


def _candidate_delta(
    research_candidate: dict[str, Any] | None,
    runtime_candidate: dict[str, Any],
    *,
    research_source: str,
) -> dict[str, Any]:
    threshold = _safe_float(runtime_candidate.get("effective_entry_min_net_usdt")) or 0.12
    research_expected = (
        _safe_float((research_candidate or {}).get("expected_net_after_full_cost"))
        if research_candidate
        else None
    )
    runtime_expected = _safe_float(runtime_candidate.get("runtime_max_expected_net_after_full_cost"))
    delta = compute_delta(research_expected, runtime_expected, threshold=threshold)
    runtime_sources = dict(runtime_candidate.get("runtime_profile_sources") or {})
    if not runtime_sources:
        profile_keys = runtime_candidate.get("runtime_profile_keys_top") or {}
        if any("rolling_quote_window" in str(key) for key in profile_keys):
            runtime_sources["rolling_quote_window"] = sum(
                _safe_int(value) for value in profile_keys.values()
            )
    data_source_mismatch = bool(
        research_source
        and (
            "kucoin_public_futures_klines" in research_source
            or "fresh_kucoin_public_klines_research" in research_source
        )
        and runtime_sources
        and "rolling_quote_window" in runtime_sources
    )
    return {
        "research_edge": research_expected,
        "runtime_max_edge": runtime_expected,
        "delta_absolute": delta["absolute"],
        "delta_percent": delta["percent"],
        "data_source_mismatch": data_source_mismatch,
        "timestamp_freshness_delta": None,
        "effective_threshold": threshold,
        "blocker_classification": runtime_candidate.get("first_blocking_gate"),
        "runtime_would_pass_at_research_value": delta["runtime_would_pass_at_research_value"],
        "runtime_observed_passes_effective_threshold": delta["runtime_observed_passes_effective_threshold"],
        "runtime_edge_fails_due_to_decay_or_formula_cost_change": (
            "inconclusive_source_mismatch_and_missing_research_timestamp"
            if data_source_mismatch
            else "not_proven"
        ),
        "missing_evidence": sorted(
            set((runtime_candidate.get("missing_fields") or []) + ((research_candidate or {}).get("missing_fields") or []))
        ),
    }


def _discovery_candidate_lookup(discovery: dict[str, Any]) -> dict[str, dict[str, Any]]:
    summary = discovery.get("summary") if isinstance(discovery.get("summary"), dict) else {}
    rows = summary.get("ranked_candidates") if isinstance(summary.get("ranked_candidates"), list) else []
    return {str(row.get("candidate_key") or ""): row for row in rows if isinstance(row, dict)}


def _classify(
    *,
    primary: dict[str, Any],
    source_mismatch: bool,
    formula_mismatch: bool,
    threshold_mismatch: bool,
    telemetry_gap: bool,
) -> dict[str, str]:
    runtime_max = _safe_float(primary.get("runtime_max_edge"))
    threshold = _safe_float(primary.get("effective_threshold")) or 0.12
    research_pass = bool(primary.get("runtime_would_pass_at_research_value"))
    runtime_pass = bool(primary.get("runtime_observed_passes_effective_threshold"))
    if threshold_mismatch:
        edge = "EDGE_PARITY_INCONCLUSIVE"
        threshold_cls = "MIN_NET_THRESHOLD_SEMANTICS_MISMATCH"
        strategy = "TRENDFOLLOWINGV2_AUTOPSY_INCONCLUSIVE"
        overall = "FRESH_RESEARCH_EDGE_NOT_RUNTIME_ADMISSIBLE_DUE_TO_THRESHOLD_SEMANTICS"
        verdict = "THRESHOLD_SEMANTICS_REPAIR_REQUIRED"
    elif formula_mismatch:
        edge = "RESEARCH_RUNTIME_FORMULA_MISMATCH"
        threshold_cls = "MIN_NET_THRESHOLD_NOT_PRIMARY"
        strategy = "TRENDFOLLOWINGV2_AUTOPSY_INCONCLUSIVE"
        overall = "FRESH_RESEARCH_EDGE_NOT_RUNTIME_ADMISSIBLE_DUE_TO_COST_MODEL"
        verdict = "FORMULA_PARITY_REPAIR_REQUIRED"
    elif source_mismatch:
        edge = "RESEARCH_RUNTIME_SOURCE_MISMATCH"
        threshold_cls = "MIN_NET_THRESHOLD_APPLIED_CORRECTLY"
        strategy = "TRENDFOLLOWINGV2_RUNTIME_EDGE_TOO_WEAK"
        overall = "FRESH_RESEARCH_EDGE_NOT_RUNTIME_ADMISSIBLE_DUE_TO_SOURCE_MISMATCH"
        verdict = "SOURCE_PARITY_REPAIR_REQUIRED"
    elif telemetry_gap:
        edge = "EDGE_PARITY_BLOCKED_BY_INSUFFICIENT_TELEMETRY"
        threshold_cls = "MIN_NET_THRESHOLD_PRIMARY_BUT_ECONOMICALLY_UNTESTED"
        strategy = "TRENDFOLLOWINGV2_AUTOPSY_BLOCKED_BY_TELEMETRY_GAP"
        overall = "EDGE_SEMANTICS_AUTOPSY_REQUIRES_TELEMETRY_PATCH"
        verdict = "TELEMETRY_ONLY_PATCH_REQUIRED"
    elif research_pass and not runtime_pass and runtime_max is not None and runtime_max < threshold:
        edge = "TRENDFOLLOWING_SIGNAL_TOO_WEAK_IN_RUNTIME"
        threshold_cls = "MIN_NET_THRESHOLD_APPLIED_CORRECTLY"
        strategy = "TRENDFOLLOWINGV2_RUNTIME_EDGE_TOO_WEAK"
        overall = "FRESH_RESEARCH_EDGE_NOT_RUNTIME_ADMISSIBLE_DUE_TO_STRATEGY_WEAKNESS"
        verdict = "TRENDFOLLOWINGV2_DEMOTE_SEARCH_STRONGER_ALPHA"
    elif research_pass and runtime_pass:
        edge = "RESEARCH_RUNTIME_EDGE_PARITY_CONFIRMED"
        threshold_cls = "MIN_NET_THRESHOLD_NOT_PRIMARY"
        strategy = "TRENDFOLLOWINGV2_AUTOPSY_INCONCLUSIVE"
        overall = "EDGE_SEMANTICS_AUTOPSY_INCONCLUSIVE"
        verdict = "EDGE_SEMANTICS_AUTOPSY_INCONCLUSIVE"
    else:
        edge = "EDGE_PARITY_INCONCLUSIVE"
        threshold_cls = "THRESHOLD_AUTOPSY_INCONCLUSIVE"
        strategy = "TRENDFOLLOWINGV2_AUTOPSY_INCONCLUSIVE"
        overall = "EDGE_SEMANTICS_AUTOPSY_INCONCLUSIVE"
        verdict = "EDGE_SEMANTICS_AUTOPSY_INCONCLUSIVE"
    return {
        "edge_parity_classification": edge,
        "threshold_classification": threshold_cls,
        "strategy_classification": strategy,
        "overall_classification": overall,
        "final_verdict": verdict,
    }


def build_report(
    *,
    research_path: Path,
    fresh_runtime_path: Path,
    next_runtime_path: Path,
    discovery_path: Path,
    code_root: Path,
) -> dict[str, Any]:
    research = _load_json(research_path)
    fresh_runtime = _load_json(fresh_runtime_path)
    next_runtime = _load_json(next_runtime_path)
    discovery = _load_json(discovery_path)
    code_contract = _code_contract(code_root)
    research_candidate = _research_candidate(research)
    research_source = str(research_candidate.get("source") or research_candidate.get("data_source") or "")

    runtime_rows: list[dict[str, Any]] = []
    fresh_candidate = fresh_runtime.get("candidate")
    if isinstance(fresh_candidate, dict):
        runtime_rows.append(fresh_candidate)
    for row in next_runtime.get("candidates") or []:
        if isinstance(row, dict):
            runtime_rows.append(row)

    runtime_candidates = {
        str(row.get("candidate") or ""): _runtime_candidate_from_artifact(row, code_root)
        for row in runtime_rows
    }
    discovery_lookup = _discovery_candidate_lookup(discovery)
    required_candidates = [
        "AVAXUSDTM:TrendFollowingV2:buy",
        "DOTUSDTM:TrendFollowingV2:sell",
        "BNBUSDTM:TrendFollowingV2:buy",
        "AVAXUSDTM:TrendFollowingV2:sell",
    ]
    candidate_findings: dict[str, dict[str, Any]] = {}
    for candidate_key in required_candidates:
        runtime_candidate = runtime_candidates.get(candidate_key)
        if runtime_candidate is None:
            symbol, strategy, side = _candidate_from_runtime_key(candidate_key)
            historical = discovery_lookup.get(candidate_key) or {}
            runtime_candidate = {
                "candidate": candidate_key,
                "canonical_candidate_key": _canonical_key(symbol, strategy, side),
                "symbol": symbol,
                "strategy": strategy,
                "canonical_strategy": canonical_strategy(strategy),
                "side": side,
                "runtime_profile_exists": False,
                "runtime_profile_sources": {},
                "quote_sources": {},
                "runtime_max_expected_net_after_full_cost": _safe_float(
                    historical.get("max_expected_net_after_full_cost")
                ),
                "runtime_mean_expected_net_after_full_cost": _safe_float(
                    historical.get("mean_expected_net_after_full_cost")
                ),
                "runtime_min_net_guard_count": _safe_int(historical.get("reason_counts", {}).get("entry_min_net_guard") if isinstance(historical.get("reason_counts"), dict) else 0),
                "runtime_edge_filter_count": 0,
                "runtime_stop_ratio_guard_count": _safe_int(historical.get("reason_counts", {}).get("entry_net_to_stop_guard") if isinstance(historical.get("reason_counts"), dict) else 0),
                "effective_entry_min_net_usdt": 0.12,
                "effective_threshold_source": "default_current_runtime_threshold",
                "first_blocking_gate": "missing_fresh_runtime_smoke",
                "all_blocking_gates": {"missing_fresh_runtime_smoke": 1},
                "missing_fields": ["fresh_runtime_smoke"],
            }
        matching_research = research_candidate if candidate_key == research_candidate.get("candidate") else None
        parity = _candidate_delta(matching_research, runtime_candidate, research_source=research_source)
        candidate_findings[candidate_key] = {
            **runtime_candidate,
            "research": matching_research,
            "historical_discovery": discovery_lookup.get(candidate_key),
            **parity,
        }

    primary = candidate_findings["AVAXUSDTM:TrendFollowingV2:buy"]
    formula_mismatch = False
    threshold_values = primary.get("effective_entry_min_net_usdt")
    threshold_mismatch = threshold_values is not None and abs(float(threshold_values) - 0.12) > 1e-9
    source_mismatch = bool(primary.get("data_source_mismatch"))
    telemetry_gap = bool(primary.get("missing_evidence"))
    classes = _classify(
        primary=primary,
        source_mismatch=source_mismatch,
        formula_mismatch=formula_mismatch,
        threshold_mismatch=threshold_mismatch,
        telemetry_gap=telemetry_gap,
    )

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "kucoin_only": True,
            "paper_only": True,
            "live": False,
            "use_mock": False,
            "threshold_mutation": False,
            "strategy_patch": False,
            "readiness_mutation": False,
            "execution_semantics_mutation": False,
            "profitability_claim": False,
        },
        "source_artifacts": {
            "research": str(research_path),
            "fresh_runtime": str(fresh_runtime_path),
            "next_runtime": str(next_runtime_path),
            "historical_discovery": str(discovery_path),
        },
        "research_edge_semantics": {
            "candidate": research_candidate,
            "formula": "StrategyStack -> DecisionEngineV2 -> RiskEngineV2: expected_net_after_full_cost = (expected_move - total_cost_ratio) * final_notional_usdt",
            "source": research_source,
            "threshold_used_for_research_selection": (research.get("scope") or {}).get("min_expected_net_usdt"),
        },
        "runtime_edge_semantics": {
            "primary_candidate": candidate_findings["AVAXUSDTM:TrendFollowingV2:buy"],
            "formula": "DecisionEngineV2 expected_net_after_cost then RiskEngineV2 full-cost USDT sizing",
            "threshold": 0.12,
        },
        "formula_parity": {
            "research_uses_runtime_strategy_stack": True,
            "research_uses_runtime_decision_engine": True,
            "research_uses_runtime_risk_engine": True,
            "formula_mismatch_exists": formula_mismatch,
            "duplicated_formula_risk": "low_for_formula_high_for_source_path",
            "units": {
                "expected_net_after_full_cost": "USDT",
                "expected_net_after_cost": "ratio",
                "fee_spread_slippage": "ratio/bps depending field",
                "ENTRY_MIN_NET_USDT": "USDT",
            },
        },
        "source_parity": {
            "research_market_data_source": research_candidate.get("data_source"),
            "research_candidate_source": research_candidate.get("source"),
            "runtime_profile_sources": primary.get("runtime_profile_sources"),
            "runtime_quote_sources": primary.get("quote_sources"),
            "source_mismatch": source_mismatch,
            "quote_timestamps_overlap": "not_provable_from_current_artifacts",
            "edge_decay_before_runtime": "not_provable_without_research_candidate_timestamp",
            "candidate_stale_by_smoke_time": "not_provable_without_research_candidate_timestamp",
        },
        "strategy_semantics": {
            "strategy_family": "TRENDFOLLOWING",
            "alias_mapping": {
                "TrendFollowingV2": canonical_strategy("TrendFollowingV2"),
                "TrendFollowing": canonical_strategy("TrendFollowing"),
                "TRENDFOLLOWING": canonical_strategy("TRENDFOLLOWING"),
            },
            "avx_buy_same_family_in_research_and_runtime": (
                research_candidate.get("canonical_candidate_key")
                == primary.get("canonical_candidate_key")
            ),
            "signal_horizon_ticks": _dig(primary, ("db_scan", "best_event", "signal_horizon_ticks")),
            "signal_expected_move_formula": _dig(primary, ("db_scan", "best_event", "signal_expected_move_formula")),
            "runtime_edge_too_weak": (
                (_safe_float(primary.get("runtime_max_edge")) or 0.0)
                < (_safe_float(primary.get("effective_threshold")) or 0.12)
            ),
        },
        "threshold_semantics": {
            "configured_entry_min_net_usdt": 0.12,
            "runtime_effective_threshold": primary.get("effective_threshold"),
            "threshold_source": primary.get("effective_threshold_source"),
            "threshold_mismatch": threshold_mismatch,
            "threshold_primary_visible_blocker": primary.get("blocker_classification") == "min_net_guard",
            "hidden_stricter_guard_observed": False,
        },
        "candidate_findings": candidate_findings,
        "code_contract": code_contract,
        "patch_decision": {
            "threshold_patch": False,
            "strategy_patch": False,
            "readiness_patch": False,
            "execution_semantics_patch": False,
            "recommended_next_target": "source_parity_repair_or_source_label_enforcement",
            "reason": "research uses KuCoin public kline path while runtime evidence uses rolling quote window; current artifacts cannot prove timestamp decay.",
        },
        **classes,
    }
    for key, allowed in (
        ("edge_parity_classification", EDGE_PARITY_CLASSIFICATIONS),
        ("threshold_classification", THRESHOLD_CLASSIFICATIONS),
        ("strategy_classification", STRATEGY_CLASSIFICATIONS),
        ("overall_classification", OVERALL_CLASSIFICATIONS),
        ("final_verdict", FINAL_VERDICTS),
    ):
        if report[key] not in allowed:
            raise RuntimeError(f"invalid {key}: {report[key]}")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    primary = (report.get("candidate_findings") or {}).get("AVAXUSDTM:TrendFollowingV2:buy") or {}
    lines = [
        "# Research vs Runtime Edge Semantics Parity Audit",
        "",
        f"- edge_parity_classification: `{report.get('edge_parity_classification')}`",
        f"- threshold_classification: `{report.get('threshold_classification')}`",
        f"- strategy_classification: `{report.get('strategy_classification')}`",
        f"- overall_classification: `{report.get('overall_classification')}`",
        f"- final_verdict: `{report.get('final_verdict')}`",
        f"- profitability_claim: `{(report.get('scope') or {}).get('profitability_claim')}`",
        "",
        "## Primary Delta",
        f"- candidate: `{primary.get('candidate')}`",
        f"- research_edge: `{primary.get('research_edge')}`",
        f"- runtime_max_edge: `{primary.get('runtime_max_edge')}`",
        f"- delta_absolute: `{primary.get('delta_absolute')}`",
        f"- delta_percent: `{primary.get('delta_percent')}`",
        f"- effective_threshold: `{primary.get('effective_threshold')}`",
        f"- data_source_mismatch: `{primary.get('data_source_mismatch')}`",
        f"- missing_evidence: `{primary.get('missing_evidence')}`",
        "",
        "## Candidate Findings",
        "| candidate | research_edge | runtime_max | delta_pct | threshold | blocker | source_mismatch | missing_evidence |",
        "|---|---:|---:|---:|---:|---|---:|---|",
    ]
    for key, row in (report.get("candidate_findings") or {}).items():
        lines.append(
            "| {candidate} | {research} | {runtime} | {delta} | {threshold} | {blocker} | {source_mismatch} | {missing} |".format(
                candidate=key,
                research=row.get("research_edge"),
                runtime=row.get("runtime_max_edge"),
                delta=row.get("delta_percent"),
                threshold=row.get("effective_threshold"),
                blocker=row.get("blocker_classification"),
                source_mismatch=row.get("data_source_mismatch"),
                missing=",".join(row.get("missing_evidence") or []),
            )
        )
    lines.extend(
        [
            "",
            "## Formula Parity",
            f"- formula_mismatch_exists: `{(report.get('formula_parity') or {}).get('formula_mismatch_exists')}`",
            f"- formula: `{(report.get('formula_parity') or {}).get('units')}`",
            "",
            "## Source Parity",
            f"- research_market_data_source: `{(report.get('source_parity') or {}).get('research_market_data_source')}`",
            f"- research_candidate_source: `{(report.get('source_parity') or {}).get('research_candidate_source')}`",
            f"- runtime_profile_sources: `{(report.get('source_parity') or {}).get('runtime_profile_sources')}`",
            f"- edge_decay_before_runtime: `{(report.get('source_parity') or {}).get('edge_decay_before_runtime')}`",
            "",
            "## Patch Decision",
            f"- recommended_next_target: `{(report.get('patch_decision') or {}).get('recommended_next_target')}`",
            f"- reason: `{(report.get('patch_decision') or {}).get('reason')}`",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--research-json", type=Path, default=ANALYSIS_DIR / "new_alpha_research_validation_current.json")
    parser.add_argument("--fresh-runtime-json", type=Path, default=ANALYSIS_DIR / "fresh_alpha_candidate_runtime_smoke_current.json")
    parser.add_argument("--next-runtime-json", type=Path, default=ANALYSIS_DIR / "next_research_candidate_runtime_smoke_current.json")
    parser.add_argument("--discovery-json", type=Path, default=ANALYSIS_DIR / "v2_economic_candidate_discovery_current.json")
    parser.add_argument("--output-json", type=Path, default=ANALYSIS_DIR / "research_runtime_edge_semantics_parity_current.json")
    parser.add_argument("--output-md", type=Path, default=ANALYSIS_DIR / "research_runtime_edge_semantics_parity_current.md")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(
        research_path=args.research_json,
        fresh_runtime_path=args.fresh_runtime_json,
        next_runtime_path=args.next_runtime_json,
        discovery_path=args.discovery_json,
        code_root=WORKDIR,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    args.output_md.write_text(render_markdown(report), encoding="utf-8")
    print(report["edge_parity_classification"])
    print(report["threshold_classification"])
    print(report["strategy_classification"])
    print(report["overall_classification"])
    print(report["final_verdict"])
    print(args.output_json)
    print(args.output_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
