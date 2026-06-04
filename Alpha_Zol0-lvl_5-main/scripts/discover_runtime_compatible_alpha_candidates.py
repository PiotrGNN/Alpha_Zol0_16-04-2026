import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any


RUNTIME_SOURCE = "rolling_quote_window"
DEFAULT_MIN_EXPECTED_NET_USDT = 0.12
DEFAULT_MAX_PROFILE_AGE_SEC = 1200.0

CLASS_CANDIDATE_FOUND = "RUNTIME_COMPATIBLE_CANDIDATE_FOUND"
CLASS_NO_CANDIDATE = "NO_RUNTIME_COMPATIBLE_CANDIDATE_FOUND"
CLASS_MISSING_PROFILE = "RUNTIME_COMPATIBLE_DISCOVERY_BLOCKED_BY_MISSING_PROFILE_DATA"
CLASS_TELEMETRY_GAP = "RUNTIME_COMPATIBLE_DISCOVERY_BLOCKED_BY_TELEMETRY_GAP"
CLASS_INCONCLUSIVE = "RUNTIME_COMPATIBLE_DISCOVERY_INCONCLUSIVE"

FAIL_SOURCE_MISMATCH = "NOT_RUNTIME_ADMISSIBLE_SOURCE_MISMATCH"
FAIL_EDGE_BELOW_THRESHOLD = "NOT_RUNTIME_ADMISSIBLE_EDGE_BELOW_THRESHOLD"
FAIL_STALE_PROFILE = "NOT_RUNTIME_ADMISSIBLE_STALE_PROFILE"
FAIL_PROFILE_MISSING = "NOT_RUNTIME_ADMISSIBLE_PROFILE_MISSING"
FAIL_TELEMETRY_GAP = "NOT_RUNTIME_ADMISSIBLE_TELEMETRY_GAP"

RUNTIME_EVENTS = {
    "entry_reject_v2",
    "entry_eval_v2",
    "position_open_v2",
}

CONTAMINATION_MARKERS = {
    "seed": ("seed", "seeded"),
    "fallback": ("fallback",),
    "force_open": ("force-open", "force_open", "diagnostic_force_open"),
    "mock": ("mock", "use_mock"),
    "forced_cycle": ("forced-cycle", "forced_cycle"),
}


def canonical_strategy(strategy: str | None) -> str | None:
    if strategy is None:
        return None
    normalized = str(strategy).strip().lower().replace("-", "_")
    aliases = {
        "trendfollowingv2": "TRENDFOLLOWING",
        "trendfollowing": "TRENDFOLLOWING",
        "trend_following": "TRENDFOLLOWING",
        "microbreakoutv2": "MICROBREAKOUT",
        "microbreakout": "MICROBREAKOUT",
        "micro_breakout": "MICROBREAKOUT",
        "momentumv2": "MOMENTUM",
        "momentum": "MOMENTUM",
        "meanreversionv2": "MEANREVERSION",
        "meanreversion": "MEANREVERSION",
        "mean_reversion": "MEANREVERSION",
    }
    return aliases.get(normalized, str(strategy).strip().upper())


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _json_loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _dig(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    numeric = _safe_float(value)
    if numeric is not None and numeric > 1_000_000_000:
        if numeric > 10_000_000_000:
            numeric = numeric / 1000.0
        return datetime.fromtimestamp(numeric, tz=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    for candidate in (text, text.replace(" ", "T")):
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _iso_or_none(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _extract_sizing_trace(payload: dict[str, Any]) -> dict[str, Any]:
    trace = _dig(payload, ("risk_block_fields", "sizing_trace"))
    if isinstance(trace, dict):
        return trace
    trace = payload.get("sizing_trace")
    if isinstance(trace, dict):
        return trace
    trace = _dig(payload, ("meta", "sizing_trace"))
    return trace if isinstance(trace, dict) else {}


def _extract_cost_breakdown(payload: dict[str, Any]) -> dict[str, Any]:
    breakdown = payload.get("cost_breakdown")
    if isinstance(breakdown, dict):
        return breakdown
    breakdown = _dig(payload, ("meta", "cost_breakdown"))
    return breakdown if isinstance(breakdown, dict) else {}


def _extract_expected_full_cost(payload: dict[str, Any], sizing_trace: dict[str, Any]) -> float | None:
    return (
        _safe_float(payload.get("expected_net_after_full_cost"))
        or _safe_float(sizing_trace.get("expected_net_after_full_cost"))
        or _safe_float(_dig(payload, ("meta", "expected_net_after_full_cost")))
    )


def _extract_entry_min_net(
    payload: dict[str, Any],
    sizing_trace: dict[str, Any],
    default_min_expected_net_usdt: float,
) -> float:
    return (
        _safe_float(payload.get("entry_min_net_usdt"))
        or _safe_float(sizing_trace.get("entry_min_net_usdt"))
        or _safe_float(_dig(payload, ("meta", "entry_min_net_usdt")))
        or float(default_min_expected_net_usdt)
    )


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    cursor = conn.execute(f"PRAGMA table_info({table_name})")
    return {str(row[1]) for row in cursor.fetchall()}


def _log_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    tables = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if "logs" not in tables:
        return []
    columns = _table_columns(conn, "logs")
    timestamp_col = "timestamp" if "timestamp" in columns else "ts" if "ts" in columns else None
    event_col = "event" if "event" in columns else "event_type" if "event_type" in columns else None
    details_col = "details" if "details" in columns else "payload" if "payload" in columns else None
    if event_col is None or details_col is None:
        return []
    selected = ["rowid", event_col, details_col]
    if timestamp_col:
        selected.append(timestamp_col)
    rows = []
    for row in conn.execute(f"SELECT {', '.join(selected)} FROM logs ORDER BY rowid ASC"):
        item = dict(zip(selected, row))
        rows.append(
            {
                "rowid": item.get("rowid"),
                "event": item.get(event_col),
                "payload": _json_loads(item.get(details_col)),
                "timestamp": item.get(timestamp_col) if timestamp_col else None,
            }
        )
    return rows


def _contamination_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {key: 0 for key in CONTAMINATION_MARKERS}
    for row in rows:
        for key, markers in CONTAMINATION_MARKERS.items():
            if _contains_positive_marker(row.get("event"), row.get("payload"), markers):
                counts[key] += 1
    return counts


def _contains_positive_marker(event: Any, payload: Any, markers: tuple[str, ...]) -> bool:
    event_text = str(event or "").lower()
    if any(marker in event_text for marker in markers):
        return True
    return _payload_contains_positive_marker(payload, markers)


def _payload_contains_positive_marker(value: Any, markers: tuple[str, ...]) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key).lower()
            if any(marker in key_text for marker in markers):
                if nested is True:
                    return True
                if isinstance(nested, (int, float)) and not isinstance(nested, bool) and nested != 0:
                    return True
                if isinstance(nested, str) and nested.strip().lower() in {"1", "true", "yes", "on"}:
                    return True
            if _payload_contains_positive_marker(nested, markers):
                return True
        return False
    if isinstance(value, list):
        return any(_payload_contains_positive_marker(item, markers) for item in value)
    if isinstance(value, str):
        text = value.lower()
        return any(f"{marker}=1" in text or f"{marker}=true" in text for marker in markers)
    return False


def _candidate_from_row(
    db_path: Path,
    row: dict[str, Any],
    contamination: dict[str, int],
    *,
    min_expected_net_usdt: float,
    max_profile_age_sec: float,
) -> dict[str, Any] | None:
    payload = row["payload"]
    if not isinstance(payload, dict):
        return None
    symbol = payload.get("symbol") or _dig(payload, ("meta", "symbol"))
    strategy = payload.get("strategy") or _dig(payload, ("meta", "strategy"))
    side = payload.get("side") or payload.get("direction") or _dig(payload, ("meta", "side"))
    if not symbol or not strategy or not side:
        return None

    sizing_trace = _extract_sizing_trace(payload)
    cost_breakdown = _extract_cost_breakdown(payload)
    runtime_profile_source = (
        payload.get("runtime_profile_source")
        or cost_breakdown.get("runtime_profile_source")
        or _dig(payload, ("meta", "runtime_profile_source"))
    )
    runtime_profile_key = (
        payload.get("runtime_profile_key")
        or cost_breakdown.get("runtime_profile_key")
        or _dig(payload, ("meta", "runtime_profile_key"))
    )
    profile_age_sec = (
        _safe_float(payload.get("runtime_profile_age_sec"))
        or _safe_float(cost_breakdown.get("runtime_profile_age_sec"))
    )
    profile_span_sec = (
        _safe_float(payload.get("runtime_profile_span_sec"))
        or _safe_float(cost_breakdown.get("runtime_profile_span_sec"))
    )
    profile_sample_size = (
        _safe_int(payload.get("runtime_profile_sample_size"))
        or _safe_int(cost_breakdown.get("runtime_profile_sample_size"))
    )
    expected_net = _extract_expected_full_cost(payload, sizing_trace)
    effective_min_net = _extract_entry_min_net(payload, sizing_trace, min_expected_net_usdt)
    profile_timestamp = _parse_timestamp(payload.get("profile_timestamp") or payload.get("ts") or row.get("timestamp"))
    quote_window_end = profile_timestamp
    quote_window_start = (
        profile_timestamp - timedelta(seconds=profile_span_sec)
        if profile_timestamp is not None and profile_span_sec is not None
        else None
    )
    runtime_profile_exists = bool(runtime_profile_source and runtime_profile_key and profile_sample_size)
    source_parity_proven = runtime_profile_source == RUNTIME_SOURCE
    source_parity_status = (
        "SOURCE_PARITY_PROVEN" if source_parity_proven else "SOURCE_PARITY_NOT_PROVEN"
    )
    clears_threshold = (
        expected_net is not None and expected_net >= effective_min_net and expected_net >= min_expected_net_usdt
    )
    clean_runtime_evidence = all(int(value) == 0 for value in contamination.values())
    is_stale = profile_age_sec is not None and profile_age_sec > max_profile_age_sec
    telemetry_gap_fields = []
    if expected_net is None:
        telemetry_gap_fields.append("expected_net_after_full_cost")
    if profile_timestamp is None:
        telemetry_gap_fields.append("profile_timestamp")
    if not clean_runtime_evidence:
        telemetry_gap_fields.append("contamination")

    if not source_parity_proven:
        classification = FAIL_SOURCE_MISMATCH
        runtime_admissible = False
    elif not runtime_profile_exists:
        classification = FAIL_PROFILE_MISSING
        runtime_admissible = False
    elif telemetry_gap_fields:
        classification = FAIL_TELEMETRY_GAP
        runtime_admissible = False
    elif is_stale:
        classification = FAIL_STALE_PROFILE
        runtime_admissible = False
    elif not clears_threshold:
        classification = FAIL_EDGE_BELOW_THRESHOLD
        runtime_admissible = False
    else:
        classification = CLASS_CANDIDATE_FOUND
        runtime_admissible = True

    canonical = canonical_strategy(str(strategy))
    return {
        "db_path": str(db_path),
        "rowid": row.get("rowid"),
        "event": row.get("event"),
        "symbol": str(symbol),
        "strategy": str(strategy),
        "canonical_strategy": canonical,
        "side": str(side).lower(),
        "candidate_key": f"{symbol}:{canonical}:{str(side).lower()}",
        "source": runtime_profile_source,
        "source_parity_status": source_parity_status,
        "profile_source": runtime_profile_source,
        "profile_timestamp": _iso_or_none(profile_timestamp),
        "quote_window_start": _iso_or_none(quote_window_start),
        "quote_window_end": _iso_or_none(quote_window_end),
        "expected_net_after_full_cost": expected_net,
        "fee_model": {
            "fee_rate": _safe_float(cost_breakdown.get("fee_rate")),
            "fee_round_trip_ratio": _safe_float(cost_breakdown.get("fee_round_trip_ratio")),
        },
        "spread_model": {
            "spread_ratio": _safe_float(cost_breakdown.get("spread_ratio")),
            "spread_bps": _safe_float(cost_breakdown.get("spread_bps")),
        },
        "slippage_model": {
            "slippage_ratio": _safe_float(cost_breakdown.get("slippage_ratio")),
            "slippage_bps": _safe_float(cost_breakdown.get("slippage_bps")),
        },
        "effective_entry_min_net_usdt": effective_min_net,
        "clears_threshold": clears_threshold,
        "runtime_profile_exists": runtime_profile_exists,
        "source_parity_proven": source_parity_proven,
        "runtime_profile_key": runtime_profile_key,
        "runtime_profile_age_sec": profile_age_sec,
        "runtime_profile_span_sec": profile_span_sec,
        "runtime_profile_sample_size": profile_sample_size,
        "max_profile_age_sec": float(max_profile_age_sec),
        "clean_runtime_evidence": clean_runtime_evidence,
        "contamination_counts": contamination,
        "telemetry_gap_fields": telemetry_gap_fields,
        "runtime_admissible": runtime_admissible,
        "runtime_admissibility_classification": classification,
    }


def scan_runtime_db(
    db_path: Path,
    *,
    min_expected_net_usdt: float = DEFAULT_MIN_EXPECTED_NET_USDT,
    max_profile_age_sec: float = DEFAULT_MAX_PROFILE_AGE_SEC,
) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = _log_rows(conn)
    finally:
        conn.close()
    contamination = _contamination_counts(rows)
    candidates = []
    for row in rows:
        if str(row.get("event")) not in RUNTIME_EVENTS:
            continue
        candidate = _candidate_from_row(
            db_path,
            row,
            contamination,
            min_expected_net_usdt=min_expected_net_usdt,
            max_profile_age_sec=max_profile_age_sec,
        )
        if candidate is not None:
            candidates.append(candidate)
    return {
        "db_path": str(db_path),
        "record_count": len(candidates),
        "contamination_counts": contamination,
        "candidates": candidates,
    }


def _classification_for_candidates(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return CLASS_MISSING_PROFILE
    if any(candidate.get("runtime_admissible") for candidate in candidates):
        return CLASS_CANDIDATE_FOUND
    classifications = {str(candidate.get("runtime_admissibility_classification")) for candidate in candidates}
    if classifications and classifications <= {FAIL_PROFILE_MISSING}:
        return CLASS_MISSING_PROFILE
    if classifications and classifications <= {FAIL_TELEMETRY_GAP}:
        return CLASS_TELEMETRY_GAP
    return CLASS_NO_CANDIDATE


def _numeric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": mean(values),
    }


def discover(
    db_paths: list[Path],
    *,
    min_expected_net_usdt: float = DEFAULT_MIN_EXPECTED_NET_USDT,
    max_profile_age_sec: float = DEFAULT_MAX_PROFILE_AGE_SEC,
) -> dict[str, Any]:
    scans = [
        scan_runtime_db(
            Path(db_path),
            min_expected_net_usdt=min_expected_net_usdt,
            max_profile_age_sec=max_profile_age_sec,
        )
        for db_path in db_paths
        if Path(db_path).exists()
    ]
    raw_candidates = [candidate for scan in scans for candidate in scan["candidates"]]
    candidates = _deduplicate_candidates(raw_candidates)
    candidates.sort(
        key=lambda candidate: (
            bool(candidate.get("runtime_admissible")),
            _safe_float(candidate.get("expected_net_after_full_cost")) or -1.0,
            0.0 - (_safe_float(candidate.get("runtime_profile_age_sec")) or 999999.0),
        ),
        reverse=True,
    )
    classification = _classification_for_candidates(candidates)
    expected_values = [
        float(candidate["expected_net_after_full_cost"])
        for candidate in candidates
        if _safe_float(candidate.get("expected_net_after_full_cost")) is not None
    ]
    runtime_admissible = [candidate for candidate in candidates if candidate.get("runtime_admissible")]
    contamination_totals = {key: 0 for key in CONTAMINATION_MARKERS}
    for scan in scans:
        for key, value in scan["contamination_counts"].items():
            contamination_totals[key] = contamination_totals.get(key, 0) + int(value)
    scan_summaries = [
        {
            "db_path": scan["db_path"],
            "record_count": scan["record_count"],
            "contamination_counts": scan["contamination_counts"],
        }
        for scan in scans
    ]
    return {
        "summary": {
            "classification": classification,
            "db_count": len(scans),
            "candidate_event_count": len(raw_candidates),
            "candidate_count": len(candidates),
            "runtime_admissible_candidate_count": len(runtime_admissible),
            "effective_entry_min_net_usdt": float(min_expected_net_usdt),
            "max_profile_age_sec": float(max_profile_age_sec),
            "runtime_source_required": RUNTIME_SOURCE,
            "expected_net_after_full_cost_stats": _numeric_summary(expected_values),
            "contamination_counts": contamination_totals,
            "best_candidate": runtime_admissible[0] if runtime_admissible else (candidates[0] if candidates else None),
        },
        "scan_summaries": scan_summaries,
        "candidates": candidates,
    }


def _candidate_rank_tuple(candidate: dict[str, Any]) -> tuple[bool, float, float, bool]:
    return (
        bool(candidate.get("runtime_admissible")),
        _safe_float(candidate.get("expected_net_after_full_cost")) or -1.0,
        0.0 - (_safe_float(candidate.get("runtime_profile_age_sec")) or 999999.0),
        not bool(candidate.get("telemetry_gap_fields")),
    )


def _deduplicate_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_key: dict[str, dict[str, Any]] = {}
    counts_by_key: dict[str, int] = {}
    for candidate in candidates:
        key = str(candidate.get("candidate_key"))
        counts_by_key[key] = counts_by_key.get(key, 0) + 1
        current = best_by_key.get(key)
        if current is None or _candidate_rank_tuple(candidate) > _candidate_rank_tuple(current):
            best_by_key[key] = dict(candidate)
    for key, candidate in best_by_key.items():
        candidate["observed_event_count"] = counts_by_key.get(key, 0)
    return list(best_by_key.values())


def render_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Runtime Compatible Alpha Candidates Current",
        "",
        "## Summary",
        f"- classification: `{summary.get('classification')}`",
        f"- db_count: `{summary.get('db_count')}`",
        f"- candidate_event_count: `{summary.get('candidate_event_count')}`",
        f"- runtime_admissible_candidate_count: `{summary.get('runtime_admissible_candidate_count')}`",
        f"- effective_entry_min_net_usdt: `{summary.get('effective_entry_min_net_usdt')}`",
        f"- runtime_source_required: `{summary.get('runtime_source_required')}`",
        f"- expected_net_after_full_cost_stats: `{summary.get('expected_net_after_full_cost_stats')}`",
        f"- contamination_counts: `{summary.get('contamination_counts')}`",
        "",
        "## Ranked Candidates",
    ]
    for candidate in report.get("candidates", [])[:20]:
        lines.append(
            "- `{key}` expected=`{expected}` min=`{minimum}` source=`{source}` "
            "profile=`{profile}` admissible=`{admissible}` class=`{classification}`".format(
                key=candidate.get("candidate_key"),
                expected=candidate.get("expected_net_after_full_cost"),
                minimum=candidate.get("effective_entry_min_net_usdt"),
                source=candidate.get("source"),
                profile=candidate.get("runtime_profile_key"),
                admissible=candidate.get("runtime_admissible"),
                classification=candidate.get("runtime_admissibility_classification"),
            )
        )
    if not report.get("candidates"):
        lines.append("- none")
    return "\n".join(lines) + "\n"


def _resolve_db_paths(root: Path, db_glob: str, max_dbs: int, explicit_dbs: list[str]) -> list[Path]:
    paths = [Path(db_path) for db_path in explicit_dbs]
    if db_glob:
        paths.extend(sorted((root / "tmp").glob(db_glob), key=lambda path: path.stat().st_mtime, reverse=True))
    unique = []
    seen = set()
    for path in paths:
        resolved = path if path.is_absolute() else root / path
        key = str(resolved)
        if key not in seen and resolved.exists():
            seen.add(key)
            unique.append(resolved)
    return unique[:max_dbs]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", action="append", default=[])
    parser.add_argument("--db-glob", default="controlled_kpi_after_*.db")
    parser.add_argument("--max-dbs", type=int, default=30)
    parser.add_argument("--min-expected-net-usdt", type=float, default=DEFAULT_MIN_EXPECTED_NET_USDT)
    parser.add_argument("--max-profile-age-sec", type=float, default=DEFAULT_MAX_PROFILE_AGE_SEC)
    parser.add_argument("--output-json", default="analysis/runtime_compatible_alpha_candidates_current.json")
    parser.add_argument("--output-md", default="analysis/runtime_compatible_alpha_candidates_current.md")
    args = parser.parse_args()

    root = Path.cwd()
    db_paths = _resolve_db_paths(root, args.db_glob, args.max_dbs, args.db)
    report = discover(
        db_paths,
        min_expected_net_usdt=args.min_expected_net_usdt,
        max_profile_age_sec=args.max_profile_age_sec,
    )
    report["inputs"] = {
        "db_paths": [str(path) for path in db_paths],
        "min_expected_net_usdt": args.min_expected_net_usdt,
        "max_profile_age_sec": args.max_profile_age_sec,
    }
    output_json = root / args.output_json
    output_md = root / args.output_md
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    output_md.write_text(render_markdown(report), encoding="utf-8")
    print(report["summary"]["classification"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
