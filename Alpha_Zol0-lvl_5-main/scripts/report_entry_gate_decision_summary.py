import argparse
import json
import sqlite3
import statistics
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

ENTRY_GATE_EVENT = "entry_gate_decision_summary"
RISK_EVENT = "risk_decision"
PRE_ENTRY_REJECTION_EVENT = "pre_entry_candidate_rejection_trace"
ALLOW_BLOCK_REJECTION_REASONS = {
    "buy_disabled",
    "sell_disabled",
    "strategy_allowlist",
    "strategy_blocklist",
    "strategy_side_allowlist",
    "strategy_side_blocklist",
    "symbol_strategy_allowlist",
    "symbol_strategy_blocklist",
    "symbol_strategy_side_allowlist",
    "symbol_strategy_side_blocklist",
}
GUARD_REJECTION_REASONS = {
    "alpha_whitelist",
    "entry_side_alpha",
    "global_strategy_alpha",
    "side_expectancy",
    "side_guard",
    "symbol_strategy_guard",
    "trendfollowing_direction_mismatch",
    "trendfollowing_strength",
}
INVALID_SIDE_REJECTION_REASONS = {"invalid_side"}
ENTRY_GATE_REQUIRED_KEYS = (
    "ts",
    "symbol",
    "side",
    "final_allow",
    "entry_gate_bucket",
    "global_block_reason",
    "local_gate_reason",
    "effective_gate_reason",
    "effective_gate_reason_origin",
    "paper_gate_active",
    "paper_gate_reason",
    "paper_gate_mode",
    "risk_allow_before_paper_gate",
    "paper_gate_override",
    "entry_decision_raw",
    "entry_decision_final",
    "entry_reason",
    "entry_reason_classification",
    "entry_live_edge",
    "entry_edge_over_fee",
    "entry_edge_after_execution",
    "spread",
    "liquidity_ok",
    "confidence",
    "fee_estimate",
    "current_edge",
    "realtime_edge",
    "max_positions_blocked",
)
ENTRY_GATE_SPREAD_KEYS = ("abs", "pct", "bps")


def _safe_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _build_anchor(cur: sqlite3.Cursor, hours: int | None):
    if hours is None:
        return None
    max_ts = cur.execute("select max(timestamp) from logs").fetchone()[0]
    if not max_ts:
        return None
    return (
        datetime.fromisoformat(str(max_ts).replace("Z", "+00:00"))
        - timedelta(hours=hours)
    ).isoformat(sep=" ")


def _load_rows(db_path: Path, hours: int | None, event: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        params = [event]
        query = (
            "select rowid, timestamp, event, details from logs "
            "where event = ?"
        )
        if hours is not None:
            anchor = _build_anchor(cur, hours)
            if anchor is not None:
                query += " and timestamp >= ?"
                params.append(anchor)
        query += " order by rowid asc"
        rows = cur.execute(query, params).fetchall()
        return rows
    finally:
        conn.close()


def _load_sequence_rows(db_path: Path, hours: int | None):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        params = [ENTRY_GATE_EVENT, RISK_EVENT]
        query = (
            "select rowid, timestamp, event, details from logs "
            "where event in (?, ?)"
        )
        if hours is not None:
            anchor = _build_anchor(cur, hours)
            if anchor is not None:
                query += " and timestamp >= ?"
                params.append(anchor)
        query += " order by rowid asc"
        return cur.execute(query, params).fetchall()
    finally:
        conn.close()


def _mean_median(values):
    numbers = [value for value in values if value is not None]
    if not numbers:
        return {"count": 0, "mean": None, "median": None}
    return {
        "count": len(numbers),
        "mean": statistics.fmean(numbers),
        "median": statistics.median(numbers),
    }


def _safe_json_loads(raw):
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _payload_health(payload):
    if not isinstance(payload, dict):
        return {
            "complete": False,
            "missing_keys": list(ENTRY_GATE_REQUIRED_KEYS),
            "missing_spread_keys": list(ENTRY_GATE_SPREAD_KEYS),
        }
    missing_keys = [key for key in ENTRY_GATE_REQUIRED_KEYS if key not in payload]
    spread_obj = payload.get("spread")
    if isinstance(spread_obj, dict):
        missing_spread_keys = [
            key for key in ENTRY_GATE_SPREAD_KEYS if key not in spread_obj
        ]
    else:
        missing_spread_keys = list(ENTRY_GATE_SPREAD_KEYS)
    return {
        "complete": not missing_keys and not missing_spread_keys,
        "missing_keys": missing_keys,
        "missing_spread_keys": missing_spread_keys,
    }


def _classify_position_open_truth(payload: dict):
    if not isinstance(payload, dict):
        return "UNKNOWN_REQUIRES_REVIEW"
    existing = str(payload.get("entry_open_truth_classification") or "").strip()
    if existing:
        return existing
    selection_source = str(payload.get("selection_source") or "").strip().lower()
    entry_reason = str(payload.get("entry_reason") or "").strip().lower()
    decision_router_path = str(payload.get("decision_router_path") or "").strip()
    decision_router_path = decision_router_path.lower()
    override_reason = str(payload.get("override_reason") or "").strip().lower()
    if (
        selection_source == "paper_auto_open_fallback"
        or decision_router_path == "paper_auto_open_fallback"
        or override_reason == "paper_auto_open_fallback"
    ):
        return "PAPER_AUTO_OPEN_FALLBACK"
    if (
        selection_source == "entry_symbol_strategy_side_allowlist"
        or decision_router_path == "paper_auto_open_allowlisted"
        or override_reason == "paper_auto_open_allowlisted"
        or entry_reason == "paper_auto_open_allowlisted"
    ):
        return "BOOTSTRAP_ALLOWLIST_ASSISTED"
    if entry_reason == "seed_trades_override":
        return "SEED_TRADES_OVERRIDE_ASSISTED"
    if entry_reason == "decision_passed" and override_reason in {"", "none"}:
        return "NATURAL_STRATEGY_ENTRY"
    if entry_reason in {
        "edge_discovered_dynamic",
        "entry_live_edge",
        "live_edge_discovered",
        "dynamic_edge_discovered",
    }:
        return "EDGE_DISCOVERED_DYNAMIC"
    return "UNKNOWN_REQUIRES_REVIEW"


def _position_open_identity(payload: dict):
    payload = payload if isinstance(payload, dict) else {}
    nested_position = payload.get("position")
    if not isinstance(nested_position, dict):
        nested_position = {}
    canonical_bucket = payload.get("canonical_bucket")
    if not isinstance(canonical_bucket, dict):
        canonical_bucket = nested_position.get("canonical_bucket")
    canonical_bucket_key = payload.get("canonical_bucket_key")
    if canonical_bucket_key in (None, "") and isinstance(canonical_bucket, dict):
        canonical_bucket_key = canonical_bucket.get("canonical_bucket_key")
    strategy = payload.get("strategy")
    if strategy in (None, ""):
        strategy = (
            nested_position.get("entry_main_strategy")
            or nested_position.get("strategy")
        )
    side = payload.get("side")
    if side in (None, ""):
        side = nested_position.get("side")
    selection_source = payload.get("selection_source")
    if selection_source in (None, ""):
        selection_source = nested_position.get("selection_source")
    entry_main_strategy = payload.get("entry_main_strategy")
    if entry_main_strategy in (None, ""):
        entry_main_strategy = nested_position.get("entry_main_strategy") or strategy
    return {
        "symbol": payload.get("symbol") or nested_position.get("symbol"),
        "strategy": strategy,
        "entry_main_strategy": entry_main_strategy,
        "side": side,
        "selection_source": selection_source,
        "decision_router_path": payload.get("decision_router_path")
        or nested_position.get("decision_router_path"),
        "override_reason": payload.get("override_reason")
        or nested_position.get("override_reason"),
        "canonical_bucket": canonical_bucket,
        "canonical_bucket_key": canonical_bucket_key,
    }


def _normalized_candidate_key(symbol, strategy, side):
    symbol_value = str(symbol or "").strip().upper() or None
    strategy_value = str(strategy or "").strip() or None
    side_value = str(side or "").strip().lower() or None
    return (symbol_value, strategy_value, side_value)


def _first_scalar(*values):
    for value in values:
        if value in (None, ""):
            continue
        if isinstance(value, (dict, list, tuple, set)):
            continue
        return value
    return None


def _candidate_fields_from_rejection(payload: dict):
    payload = payload if isinstance(payload, dict) else {}
    preview = payload.get("candidate_payload_preview")
    if not isinstance(preview, dict):
        preview = {}
    strategy = _first_scalar(
        payload.get("normalized_strategy_value"),
        preview.get("strategy"),
        preview.get("main_strategy"),
        preview.get("selected_strategy"),
        preview.get("_strategy"),
    )
    side = _first_scalar(
        payload.get("normalized_side_value"),
        preview.get("raw_side"),
        preview.get("side"),
        preview.get("signal"),
        preview.get("direction"),
        preview.get("_side"),
    )
    return _normalized_candidate_key(payload.get("symbol"), strategy, side)


def _candidate_records(counter: Counter):
    records = []
    for (symbol, strategy, side), count in sorted(
        counter.items(),
        key=lambda item: (
            str(item[0][0] or ""),
            str(item[0][1] or ""),
            str(item[0][2] or ""),
        ),
    ):
        records.append(
            {
                "symbol": symbol,
                "strategy": strategy,
                "side": side,
                "count": count,
            }
        )
    return records


def _candidate_reason_records(counter: Counter):
    records = []
    for (symbol, strategy, side, reason), count in sorted(
        counter.items(),
        key=lambda item: (
            str(item[0][0] or ""),
            str(item[0][1] or ""),
            str(item[0][2] or ""),
            str(item[0][3] or ""),
        ),
    ):
        records.append(
            {
                "symbol": symbol,
                "strategy": strategy,
                "side": side,
                "reason": reason,
                "count": count,
            }
        )
    return records


def _raw_side_text(value):
    if value is None:
        return None
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        return text or None
    if isinstance(value, list):
        return "signals:empty" if not value else "signals:list"
    if isinstance(value, dict):
        return None
    return type(value).__name__


def _raw_side_values_from_rejection(payload: dict):
    payload = payload if isinstance(payload, dict) else {}
    values = []
    candidates = payload.get("raw_side_candidates")
    if isinstance(candidates, list):
        for item in candidates:
            if isinstance(item, dict):
                raw = _raw_side_text(item.get("raw_value"))
            else:
                raw = _raw_side_text(item)
            if raw and not raw.startswith("dict:"):
                values.append(raw)
    preview = payload.get("candidate_payload_preview")
    if isinstance(preview, dict):
        for key in ("raw_side", "_side", "side", "direction", "action", "signal"):
            if key in preview:
                raw = _raw_side_text(preview.get(key))
                if raw:
                    values.append(raw)
    normalized_side = _raw_side_text(payload.get("normalized_side_value"))
    if normalized_side and not values:
        values.append(normalized_side)
    return values


def _raw_side_value_records(counter: Counter):
    return [
        {"raw_side": raw_side, "count": count}
        for raw_side, count in sorted(
            counter.items(),
            key=lambda item: (-int(item[1]), str(item[0])),
        )[:20]
    ]


def _entry_assignment_fields(payload: dict):
    payload = payload if isinstance(payload, dict) else {}
    trace = payload.get("natural_path_trace")
    if not isinstance(trace, dict):
        trace = {}
    strategy = (
        payload.get("main_strategy")
        or payload.get("strategy")
        or payload.get("selected_strategy")
        or trace.get("main_strategy")
        or trace.get("strategy")
        or trace.get("selected_strategy")
    )
    side = payload.get("side") or trace.get("side")
    return trace, strategy, side


def _is_filter_guard_rejection(reason: str):
    reason = str(reason or "").strip()
    return (
        reason in GUARD_REJECTION_REASONS
        or reason.endswith("_guard")
        or "alpha" in reason
        or "expectancy" in reason
    )


def _build_natural_entry_candidate_contract(
    *,
    entry_payloads: list[dict],
    rejection_payloads: list[dict],
    open_truth_reasons: Counter,
):
    router_candidate_sides = Counter()
    allowed_sides = Counter()
    blocked_sides = Counter()
    guard_rejected_sides = Counter()
    invalid_side_candidates = Counter()
    rejection_reason_counts = Counter()
    raw_side_value_counts = Counter()
    router_candidate_rows = 0
    empty_assignment_rows = 0
    natural_admitted_count = 0
    assisted_seed_admitted_count = 0
    assisted_seed_allowed_sides = Counter()

    for payload in entry_payloads:
        trace, strategy, side = _entry_assignment_fields(payload)
        entry_reason = str(payload.get("entry_reason") or "").strip().lower()
        is_assisted_seed_admission = bool(payload.get("final_allow")) and (
            entry_reason == "seed_trades_override"
        )
        pre_entry_candidate_exists = bool(
            trace.get("pre_entry_candidate_exists")
            or payload.get("pre_entry_candidate_exists")
        )
        assignment_stage = str(
            trace.get("strategy_assignment_stage")
            or payload.get("strategy_assignment_stage")
            or ""
        ).strip()
        if pre_entry_candidate_exists:
            router_candidate_rows += 1
        if is_assisted_seed_admission:
            assisted_seed_admitted_count += 1
        elif payload.get("final_allow"):
            natural_admitted_count += 1
        if strategy and str(side or "").strip().lower() in {"buy", "sell"}:
            candidate_key = _normalized_candidate_key(
                payload.get("symbol"), strategy, side
            )
            allowed_sides[candidate_key] += 1
            if is_assisted_seed_admission:
                assisted_seed_allowed_sides[candidate_key] += 1
        if (
            pre_entry_candidate_exists
            and assignment_stage == "pre_entry_candidate_rejection"
            and not strategy
        ):
            empty_assignment_rows += 1

    for payload in rejection_payloads:
        symbol, strategy, side = _candidate_fields_from_rejection(payload)
        reason = str(payload.get("rejection_reason_code") or "").strip()
        raw_side_value_counts.update(_raw_side_values_from_rejection(payload))
        if symbol or strategy or side:
            router_candidate_sides[(symbol, strategy, side)] += 1
        if reason:
            rejection_reason_counts[reason] += 1
        reason_key = (symbol, strategy, side, reason or None)
        if (
            reason in ALLOW_BLOCK_REJECTION_REASONS
            or "allowlist" in reason
            or "blocklist" in reason
        ):
            blocked_sides[reason_key] += 1
        elif reason in INVALID_SIDE_REJECTION_REASONS:
            invalid_side_candidates[reason_key] += 1
        elif _is_filter_guard_rejection(reason):
            guard_rejected_sides[reason_key] += 1

    final_surviving_candidate_count = sum(allowed_sides.values())
    rejected_candidate_count = len(rejection_payloads)
    fallback_open_count = int(open_truth_reasons.get("PAPER_AUTO_OPEN_FALLBACK", 0))
    assisted_seed_open_count = int(
        open_truth_reasons.get("SEED_TRADES_OVERRIDE_ASSISTED", 0)
    )
    router_candidates_exist = bool(router_candidate_rows or rejected_candidate_count)
    fallback_trade_only = fallback_open_count > 0 and natural_admitted_count == 0
    assisted_seed_evidence_only = natural_admitted_count == 0 and (
        assisted_seed_admitted_count > 0 or assisted_seed_open_count > 0
    )
    no_natural_candidate = (
        router_candidates_exist
        and natural_admitted_count == 0
        and (
            final_surviving_candidate_count == 0
            or empty_assignment_rows > 0
            or fallback_trade_only
        )
    )
    classification = (
        "NO_NATURAL_ENTRY_CANDIDATE"
        if no_natural_candidate
        else (
            "NATURAL_ENTRY_CANDIDATE_PRESENT"
            if router_candidates_exist
            else "NO_ROUTER_CANDIDATES_OBSERVED"
        )
    )

    reason_codes = []
    if router_candidates_exist:
        reason_codes.append("ROUTER_CANDIDATES_EXIST")
    if empty_assignment_rows:
        reason_codes.append("FILTER_TO_NONE_BEFORE_ASSIGNMENT")
    if router_candidates_exist and final_surviving_candidate_count == 0:
        reason_codes.append("ADMISSION_SIDE_FILTER_INTERSECTION_EMPTY")
    if router_candidates_exist and natural_admitted_count == 0:
        reason_codes.append("NO_NATURAL_ADMISSION")
    if classification == "NO_ROUTER_CANDIDATES_OBSERVED":
        reason_codes.append("NO_ROUTER_CANDIDATES_OBSERVED")
    if blocked_sides:
        reason_codes.append("ALLOWLIST_BLOCKLIST_REJECTIONS_PRESENT")
    if guard_rejected_sides:
        reason_codes.append("GUARD_REJECTIONS_PRESENT")
    if invalid_side_candidates:
        reason_codes.append("SIDE_INVALIDATION_PRESENT")
    if assisted_seed_admitted_count:
        reason_codes.append("ASSISTED_SEED_ADMISSIONS_PRESENT")
    if assisted_seed_open_count:
        reason_codes.append("ASSISTED_SEED_OPEN_PRESENT")
    if fallback_open_count:
        reason_codes.append("FALLBACK_OPEN_PRESENT")
    if fallback_trade_only:
        reason_codes.append("FALLBACK_ECONOMICS_NOT_STRATEGY_EVIDENCE")
    if assisted_seed_evidence_only:
        reason_codes.append("ASSISTED_SEED_EVIDENCE_ONLY")

    if fallback_trade_only:
        strategy_evidence_classification = "FALLBACK_ECONOMICS_NOT_STRATEGY_EVIDENCE"
    elif assisted_seed_evidence_only:
        strategy_evidence_classification = "ASSISTED_SEED_EVIDENCE_ONLY"
    elif classification == "NO_ROUTER_CANDIDATES_OBSERVED":
        strategy_evidence_classification = "NO_ROUTER_CANDIDATES_OBSERVED"
    elif classification == "NO_NATURAL_ENTRY_CANDIDATE":
        strategy_evidence_classification = "NO_NATURAL_ENTRY_CANDIDATE"
    elif natural_admitted_count <= 0:
        strategy_evidence_classification = "NO_NATURAL_ADMISSION"
    else:
        strategy_evidence_classification = "USABLE_STRATEGY_EVIDENCE"

    usable_strategy_economics = (
        natural_admitted_count > 0
        and classification not in {
            "NO_NATURAL_ENTRY_CANDIDATE",
            "NO_ROUTER_CANDIDATES_OBSERVED",
        }
        and not fallback_trade_only
        and not assisted_seed_evidence_only
    )

    return {
        "classification": classification,
        "usable_strategy_economics": usable_strategy_economics,
        "strategy_evidence_classification": strategy_evidence_classification,
        "assisted_seed_evidence_only": assisted_seed_evidence_only,
        "router_candidate_rows": router_candidate_rows,
        "rejected_candidate_count": rejected_candidate_count,
        "empty_assignment_rows": empty_assignment_rows,
        "final_surviving_candidate_count": final_surviving_candidate_count,
        "natural_admitted_count": natural_admitted_count,
        "assisted_seed_admitted_count": assisted_seed_admitted_count,
        "assisted_seed_open_count": assisted_seed_open_count,
        "fallback_open_count": fallback_open_count,
        "router_candidate_sides": _candidate_records(router_candidate_sides),
        "allowed_sides": _candidate_records(allowed_sides),
        "assisted_seed_allowed_sides": _candidate_records(
            assisted_seed_allowed_sides
        ),
        "blocked_sides": _candidate_reason_records(blocked_sides),
        "guard_rejected_sides": _candidate_reason_records(guard_rejected_sides),
        "invalid_side_candidates": _candidate_reason_records(
            invalid_side_candidates
        ),
        "raw_side_value_counts_top20": _raw_side_value_records(
            raw_side_value_counts
        ),
        "rejection_reason_counts": rejection_reason_counts.most_common(20),
        "reason_codes": reason_codes,
    }


def build_report(db_path: Path, hours: int | None):
    db_path = db_path.resolve()
    rows = _load_rows(db_path, hours, ENTRY_GATE_EVENT)
    risk_rows = _load_rows(db_path, hours, RISK_EVENT)
    open_rows = _load_rows(db_path, hours, "position_open")
    rejection_rows = _load_rows(db_path, hours, PRE_ENTRY_REJECTION_EVENT)
    sequence_rows = _load_sequence_rows(db_path, hours)
    admitted = 0
    blocked = 0
    global_reasons = Counter()
    local_reasons = Counter()
    open_truth_reasons = Counter()
    paper_gate_overrides = 0
    complete_payloads = 0
    incomplete_samples = []
    last_payload = {}
    last_risk_payload = {}
    last_open_payload = {}
    pair_count = 0
    symbol_mismatch_pairs = 0
    pending_summary = None
    metrics = {
        "admitted": {
            "current_edge": [],
            "realtime_edge": [],
            "spread_bps": [],
            "confidence": [],
        },
        "blocked": {
            "current_edge": [],
            "realtime_edge": [],
            "spread_bps": [],
            "confidence": [],
        },
    }
    entry_payloads = []
    rejection_payloads = []
    for row in rows:
        payload = _safe_json_loads(row["details"])
        if not isinstance(payload, dict):
            continue
        entry_payloads.append(payload)
        last_payload = payload
        health = _payload_health(payload)
        if health["complete"]:
            complete_payloads += 1
        elif len(incomplete_samples) < 10:
            incomplete_samples.append(
                {
                    "rowid": row["rowid"],
                    "timestamp": row["timestamp"],
                    "symbol": payload.get("symbol"),
                    "missing_keys": health["missing_keys"],
                    "missing_spread_keys": health["missing_spread_keys"],
                }
            )
        is_admitted = bool(payload.get("final_allow"))
        bucket = "admitted" if is_admitted else "blocked"
        if is_admitted:
            admitted += 1
        else:
            blocked += 1
        global_reason = payload.get("global_block_reason")
        local_reason = payload.get("local_gate_reason")
        if global_reason:
            global_reasons[str(global_reason)] += 1
        if local_reason:
            local_reasons[str(local_reason)] += 1
        if payload.get("paper_gate_override"):
            paper_gate_overrides += 1
        spread = (
            payload.get("spread")
            if isinstance(payload.get("spread"), dict)
            else {}
        )
        metrics[bucket]["current_edge"].append(_safe_float(payload.get("current_edge")))
        metrics[bucket]["realtime_edge"].append(
            _safe_float(payload.get("realtime_edge"))
        )
        metrics[bucket]["spread_bps"].append(_safe_float(spread.get("bps")))
        metrics[bucket]["confidence"].append(_safe_float(payload.get("confidence")))
    for row in risk_rows:
        last_risk_payload = _safe_json_loads(row["details"])
    for row in open_rows:
        payload = _safe_json_loads(row["details"])
        if not isinstance(payload, dict):
            continue
        last_open_payload = payload
        open_truth = _classify_position_open_truth(payload)
        if open_truth:
            open_truth_reasons[str(open_truth)] += 1
    for row in rejection_rows:
        payload = _safe_json_loads(row["details"])
        if isinstance(payload, dict):
            rejection_payloads.append(payload)
    for row in sequence_rows:
        payload = _safe_json_loads(row["details"])
        if row["event"] == ENTRY_GATE_EVENT:
            pending_summary = payload
        elif row["event"] == RISK_EVENT:
            if pending_summary is not None:
                pair_count += 1
                if pending_summary.get("symbol") != payload.get("symbol"):
                    symbol_mismatch_pairs += 1
            pending_summary = None
    trailing_summary_rows = 1 if pending_summary is not None else 0
    relaxed_count_matches = (
        len(rows) == len(risk_rows)
        or (
            len(rows) == len(risk_rows) + 1
            and trailing_summary_rows == 1
            and symbol_mismatch_pairs == 0
        )
    )
    last_health = _payload_health(last_payload)
    return {
        "db_path": str(db_path),
        "hours": hours,
        "event": ENTRY_GATE_EVENT,
        "rows": len(rows),
        "risk_decision_rows": len(risk_rows),
        "count_alignment": {
            "entry_gate_decision_summary": len(rows),
            "risk_decision": len(risk_rows),
            "delta": len(rows) - len(risk_rows),
            "count_matches": relaxed_count_matches,
        },
        "ordering": {
            "summary_before_risk_pairs": pair_count,
            "risk_without_summary": max(0, len(risk_rows) - pair_count),
            "summary_without_risk": max(0, len(rows) - pair_count),
            "trailing_summary_rows": trailing_summary_rows,
            "symbol_mismatch_pairs": symbol_mismatch_pairs,
            "all_pairs_in_order": (
                symbol_mismatch_pairs == 0
                and max(0, len(risk_rows) - pair_count) == 0
                and max(0, len(rows) - pair_count) <= 1
            ),
        },
        "payload_completeness": {
            "required_keys": list(ENTRY_GATE_REQUIRED_KEYS),
            "required_spread_keys": list(ENTRY_GATE_SPREAD_KEYS),
            "complete_rows": complete_payloads,
            "incomplete_rows": len(rows) - complete_payloads,
            "all_complete": len(rows) > 0 and complete_payloads == len(rows),
            "sample_incomplete_rows": incomplete_samples,
        },
        "admitted_vs_blocked": {"admitted": admitted, "blocked": blocked},
        "top_global_block_reason": global_reasons.most_common(10),
        "top_local_gate_reason": local_reasons.most_common(10),
        "paper_gate_overrides": paper_gate_overrides,
        "last_entry_gate_decision_summary": {
            "symbol": last_payload.get("symbol"),
            "side": last_payload.get("side"),
            "final_allow": last_payload.get("final_allow"),
            "paper_gate_active": last_payload.get("paper_gate_active"),
            "missing_keys": last_health["missing_keys"],
            "missing_spread_keys": last_health["missing_spread_keys"],
        },
        "last_risk_decision": {
            "symbol": last_risk_payload.get("symbol"),
            "entry_decision": last_risk_payload.get("entry_decision"),
            "allow": last_risk_payload.get("allow"),
        },
        "position_open_rows": len(open_rows),
        "position_open_truth_classification_counts": open_truth_reasons.most_common(10),
        "natural_entry_candidate_contract": _build_natural_entry_candidate_contract(
            entry_payloads=entry_payloads,
            rejection_payloads=rejection_payloads,
            open_truth_reasons=open_truth_reasons,
        ),
        "last_position_open": {
            **_position_open_identity(last_open_payload),
            "entry_reason": last_open_payload.get("entry_reason"),
            "entry_open_truth_classification": _classify_position_open_truth(
                last_open_payload
            ),
        },
        "metrics": {
            bucket: {
                "current_edge": _mean_median(values["current_edge"]),
                "realtime_edge": _mean_median(values["realtime_edge"]),
                "spread_bps": _mean_median(values["spread_bps"]),
                "confidence": _mean_median(values["confidence"]),
            }
            for bucket, values in metrics.items()
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="Report PAPER entry gate decision summary metrics from zol0.db"
    )
    parser.add_argument(
        "--db-path",
        default="zol0.db",
        help="Path to sqlite database. Default: zol0.db",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help=(
            "Lookback window in hours based on max log timestamp. "
            "Use 0 to disable filtering."
        ),
    )
    args = parser.parse_args()
    hours = args.hours if args.hours and args.hours > 0 else None
    report = build_report(Path(args.db_path), hours)
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
