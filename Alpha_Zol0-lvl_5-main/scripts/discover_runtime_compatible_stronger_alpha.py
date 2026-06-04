from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any


WORKDIR = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = WORKDIR / "analysis"
RUNTIME_SOURCE = "rolling_quote_window"
DEFAULT_RUNTIME_REPORT = ANALYSIS_DIR / "runtime_compatible_alpha_candidates_current.json"

STRONGER_FAMILIES = ("MICROBREAKOUT", "MOMENTUM", "MEANREVERSION")
BASELINE_FAMILIES = ("TRENDFOLLOWING",)

CLASS_FOUND = "STRONGER_RUNTIME_COMPATIBLE_CANDIDATE_FOUND"
CLASS_NONE = "NO_STRONGER_RUNTIME_COMPATIBLE_CANDIDATE_FOUND"
CLASS_PROFILE = "STRONGER_ALPHA_DISCOVERY_BLOCKED_BY_PROFILE_DATA"
CLASS_TELEMETRY = "STRONGER_ALPHA_DISCOVERY_BLOCKED_BY_TELEMETRY_GAP"
CLASS_INCONCLUSIVE = "STRONGER_ALPHA_DISCOVERY_INCONCLUSIVE"

FAIL_EDGE = "NOT_RUNTIME_ADMISSIBLE_EDGE_BELOW_THRESHOLD"
FAIL_RATIO = "NOT_RUNTIME_ADMISSIBLE_RATIO_BELOW_REQUIRED"
FAIL_EDGE_FILTERED = "NOT_RUNTIME_ADMISSIBLE_EDGE_FILTERED"
FAIL_STALE = "NOT_RUNTIME_ADMISSIBLE_STALE_PROFILE"
FAIL_PROFILE = "NOT_RUNTIME_ADMISSIBLE_PROFILE_MISSING"
FAIL_SOURCE = "NOT_RUNTIME_ADMISSIBLE_SOURCE_MISMATCH"
FAIL_TELEMETRY = "NOT_RUNTIME_ADMISSIBLE_TELEMETRY_GAP"


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
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


def canonical_strategy(strategy: Any) -> str:
    normalized = str(strategy or "").strip().lower().replace("-", "_").replace(" ", "")
    aliases = {
        "microbreakoutv2": "MICROBREAKOUT",
        "microbreakout": "MICROBREAKOUT",
        "micro_breakout": "MICROBREAKOUT",
        "momentumv2": "MOMENTUM",
        "momentum": "MOMENTUM",
        "meanreversionv2": "MEANREVERSION",
        "meanreversion": "MEANREVERSION",
        "mean_reversion": "MEANREVERSION",
        "trendfollowingv2": "TRENDFOLLOWING",
        "trendfollowing": "TRENDFOLLOWING",
        "trend_following": "TRENDFOLLOWING",
    }
    return aliases.get(normalized, str(strategy or "").strip().upper())


def strategy_family_priority(strategy: Any) -> int:
    priorities = {
        "MICROBREAKOUT": 0,
        "MOMENTUM": 1,
        "MEANREVERSION": 2,
        "TRENDFOLLOWING": 3,
    }
    return priorities.get(canonical_strategy(strategy), 99)


def _contamination_clean(counts: dict[str, Any]) -> bool:
    return all(_safe_int(counts.get(key), 0) == 0 for key in ("seed", "fallback", "mock", "force_open", "forced_cycle"))


def classify_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    expected = _safe_float(candidate.get("expected_net_after_full_cost"))
    threshold = _safe_float(candidate.get("effective_entry_min_net_usdt")) or 0.12
    ratio = _safe_float(candidate.get("entry_net_to_stop_ratio"))
    required_ratio = _safe_float(candidate.get("effective_entry_min_net_to_stop_ratio"))
    edge_filter_passes = bool(candidate.get("edge_filter_passes", expected is not None))
    profile_age = _safe_float(candidate.get("runtime_profile_age_sec"))
    max_profile_age = _safe_float(candidate.get("max_profile_age_sec")) or 1200.0
    source_parity = bool(candidate.get("source_parity_proven")) or str(candidate.get("source_parity_status")) == "SOURCE_PARITY_PROVEN"
    runtime_profile_exists = bool(candidate.get("runtime_profile_exists"))
    contamination_counts = candidate.get("contamination_counts") if isinstance(candidate.get("contamination_counts"), dict) else {}
    profile_stale = bool(candidate.get("profile_stale")) or (
        profile_age is not None and profile_age > max_profile_age
    )
    telemetry_gap_fields = list(candidate.get("telemetry_gap_fields") or [])
    if expected is None:
        telemetry_gap_fields.append("expected_net_after_full_cost")

    if not source_parity or candidate.get("source") != RUNTIME_SOURCE:
        classification = FAIL_SOURCE
    elif not runtime_profile_exists:
        classification = FAIL_PROFILE
    elif telemetry_gap_fields:
        classification = FAIL_TELEMETRY
    elif profile_stale:
        classification = FAIL_STALE
    elif not _contamination_clean(contamination_counts):
        classification = FAIL_TELEMETRY
    elif not edge_filter_passes:
        classification = FAIL_EDGE_FILTERED
    elif expected is None or expected < threshold:
        classification = FAIL_EDGE
    elif required_ratio is not None and ratio is not None and ratio < required_ratio:
        classification = FAIL_RATIO
    elif required_ratio is not None and ratio is None:
        classification = FAIL_TELEMETRY
    else:
        classification = CLASS_FOUND

    return {
        "classification": classification,
        "runtime_admissible": classification == CLASS_FOUND,
        "min_net_passes": bool(expected is not None and expected >= threshold),
        "ratio_guard_passes": (
            None
            if required_ratio is None or ratio is None
            else bool(ratio >= required_ratio)
        ),
        "edge_filter_passes": edge_filter_passes,
        "profile_stale": profile_stale,
        "telemetry_gap_fields": sorted(set(telemetry_gap_fields)),
    }


def _candidate_key(row: dict[str, Any]) -> str:
    symbol = str(row.get("symbol") or "").strip().upper()
    side = str(row.get("side") or "").strip().lower()
    return f"{symbol}:{canonical_strategy(row.get('strategy') or row.get('canonical_strategy'))}:{side}"


def normalize_candidate(row: dict[str, Any]) -> dict[str, Any]:
    canonical = canonical_strategy(row.get("canonical_strategy") or row.get("strategy"))
    cost = row.get("cost_breakdown") if isinstance(row.get("cost_breakdown"), dict) else {}
    fee_model = row.get("fee_model") if isinstance(row.get("fee_model"), dict) else {}
    spread_model = row.get("spread_model") if isinstance(row.get("spread_model"), dict) else {}
    slippage_model = row.get("slippage_model") if isinstance(row.get("slippage_model"), dict) else {}
    stop_risk = _safe_float(row.get("estimated_stop_loss_net_usdt") or row.get("stop_risk"))
    expected = _safe_float(row.get("expected_net_after_full_cost"))
    ratio = _safe_float(row.get("entry_net_to_stop_ratio"))
    if ratio is None and expected is not None and stop_risk and stop_risk > 0:
        ratio = expected / stop_risk
    normalized = {
        "symbol": str(row.get("symbol") or "").strip().upper(),
        "strategy": str(row.get("strategy") or canonical),
        "canonical_strategy": canonical,
        "side": str(row.get("side") or "").strip().lower(),
        "candidate_key": str(row.get("candidate_key") or _candidate_key(row)),
        "source": row.get("source"),
        "source_parity_status": row.get("source_parity_status"),
        "source_parity_proven": bool(row.get("source_parity_proven")),
        "profile_source": row.get("profile_source"),
        "profile_timestamp": row.get("profile_timestamp"),
        "quote_window_start": row.get("quote_window_start"),
        "quote_window_end": row.get("quote_window_end"),
        "expected_net_after_full_cost": expected,
        "expected_net_before_cost": _safe_float(row.get("expected_net_before_cost") or row.get("expected_net_before_fee")),
        "fee_estimate": _safe_float(row.get("fee_estimate") or fee_model.get("fee_round_trip_ratio") or cost.get("fee_round_trip_ratio")),
        "spread_estimate": _safe_float(row.get("spread_estimate") or spread_model.get("spread_ratio") or cost.get("spread_ratio")),
        "slippage_estimate": _safe_float(row.get("slippage_estimate") or slippage_model.get("slippage_ratio") or cost.get("slippage_ratio")),
        "execution_cost_floor": _safe_float(row.get("execution_cost_floor") or cost.get("execution_cost_floor") or cost.get("total_cost_ratio")),
        "stop_risk": stop_risk,
        "entry_net_to_stop_ratio": ratio,
        "effective_entry_min_net_usdt": _safe_float(row.get("effective_entry_min_net_usdt")) or 0.12,
        "effective_entry_min_net_to_stop_ratio": _safe_float(row.get("effective_entry_min_net_to_stop_ratio") or row.get("entry_min_net_to_stop_ratio")),
        "runtime_profile_exists": bool(row.get("runtime_profile_exists")),
        "runtime_profile_age_sec": _safe_float(row.get("runtime_profile_age_sec")),
        "max_profile_age_sec": _safe_float(row.get("max_profile_age_sec")) or 1200.0,
        "edge_filter_passes": bool(row.get("edge_filter_passes", expected is not None)),
        "contamination_counts": row.get("contamination_counts") if isinstance(row.get("contamination_counts"), dict) else {},
        "observed_event_count": _safe_int(row.get("observed_event_count"), 0),
        "db_path": row.get("db_path"),
    }
    classification = classify_candidate(normalized)
    normalized.update(
        {
            "min_net_passes": classification["min_net_passes"],
            "ratio_guard_passes": classification["ratio_guard_passes"],
            "edge_filter_passes": classification["edge_filter_passes"],
            "runtime_admissible": classification["runtime_admissible"],
            "runtime_admissibility_classification": classification["classification"],
            "telemetry_gap_fields": classification["telemetry_gap_fields"],
            "profile_stale": classification["profile_stale"],
        }
    )
    return normalized


def _numeric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {"count": len(values), "min": min(values), "max": max(values), "mean": float(mean(values))}


def _best_per_family(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        family = str(candidate.get("canonical_strategy") or "")
        current = best.get(family)
        if current is None or _rank_tuple(candidate) > _rank_tuple(current):
            best[family] = candidate
    return best


def _rank_tuple(candidate: dict[str, Any]) -> tuple[int, bool, float, float]:
    return (
        -strategy_family_priority(candidate.get("canonical_strategy")),
        bool(candidate.get("runtime_admissible")),
        _safe_float(candidate.get("expected_net_after_full_cost")) or -1.0,
        _safe_float(candidate.get("entry_net_to_stop_ratio")) or -1.0,
    )


def _classify_report(candidates: list[dict[str, Any]], stronger: list[dict[str, Any]]) -> str:
    if any(candidate.get("runtime_admissible") for candidate in stronger):
        return CLASS_FOUND
    if not candidates:
        return CLASS_PROFILE
    classifications = {str(candidate.get("runtime_admissibility_classification")) for candidate in candidates}
    if classifications <= {FAIL_PROFILE}:
        return CLASS_PROFILE
    if classifications <= {FAIL_TELEMETRY}:
        return CLASS_TELEMETRY
    if not stronger:
        return CLASS_NONE
    return CLASS_NONE


def discover_from_runtime_report(runtime_report_path: Path) -> dict[str, Any]:
    runtime_report = json.loads(Path(runtime_report_path).read_text(encoding="utf-8"))
    summary = runtime_report.get("summary") if isinstance(runtime_report.get("summary"), dict) else {}
    raw_candidates = runtime_report.get("candidates") if isinstance(runtime_report.get("candidates"), list) else []
    candidates = [normalize_candidate(row) for row in raw_candidates if isinstance(row, dict)]
    candidates.sort(key=_rank_tuple, reverse=True)
    stronger = [
        candidate
        for candidate in candidates
        if str(candidate.get("canonical_strategy")) in STRONGER_FAMILIES
    ]
    baseline = [
        candidate
        for candidate in candidates
        if str(candidate.get("canonical_strategy")) in BASELINE_FAMILIES
    ]
    final_selected = next((candidate for candidate in stronger if candidate.get("runtime_admissible")), None)
    classification = _classify_report(candidates, stronger)
    expected_values = [
        float(candidate["expected_net_after_full_cost"])
        for candidate in candidates
        if _safe_float(candidate.get("expected_net_after_full_cost")) is not None
    ]
    ratio_values = [
        float(candidate["entry_net_to_stop_ratio"])
        for candidate in candidates
        if _safe_float(candidate.get("entry_net_to_stop_ratio")) is not None
    ]
    counts_by_family: dict[str, int] = {}
    for candidate in candidates:
        family = str(candidate.get("canonical_strategy") or "UNKNOWN")
        counts_by_family[family] = counts_by_family.get(family, 0) + 1
    promotion_pass = [candidate for candidate in stronger if candidate.get("runtime_admissible")]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "classification": classification,
        "scope": {
            "kucoin_only": True,
            "paper_only": True,
            "live": False,
            "use_mock": False,
            "source_required": RUNTIME_SOURCE,
            "public_klines_used_as_runtime_proof": False,
            "threshold_mutation": False,
            "ratio_guard_weakening": False,
            "strategy_patch": False,
            "profitability_claim": False,
        },
        "source_runtime_report": str(runtime_report_path),
        "summary": {
            "db_count": _safe_int(summary.get("db_count"), 0),
            "runtime_events_scanned": _safe_int(summary.get("candidate_event_count"), 0),
            "unique_candidate_count": len(candidates),
            "candidate_count_per_strategy_family": counts_by_family,
            "best_candidate_per_family": _best_per_family(candidates),
            "candidates_above_0_05": sum(1 for value in expected_values if value >= 0.05),
            "candidates_above_0_08": sum(1 for value in expected_values if value >= 0.08),
            "candidates_above_0_10": sum(1 for value in expected_values if value >= 0.10),
            "candidates_above_0_12": sum(1 for value in expected_values if value >= 0.12),
            "candidates_passing_ratio_guard": sum(
                1
                for candidate in candidates
                if candidate.get("ratio_guard_passes") is True
            ),
            "promotion_contract_pass_count": len(promotion_pass),
            "expected_net_after_full_cost_stats": _numeric_summary(expected_values),
            "entry_net_to_stop_ratio_stats": _numeric_summary(ratio_values),
        },
        "top_20_by_expected_net_after_full_cost": sorted(
            candidates,
            key=lambda candidate: _safe_float(candidate.get("expected_net_after_full_cost")) or -1.0,
            reverse=True,
        )[:20],
        "top_20_by_expected_net_to_stop_ratio": sorted(
            candidates,
            key=lambda candidate: _safe_float(candidate.get("entry_net_to_stop_ratio")) or -1.0,
            reverse=True,
        )[:20],
        "stronger_family_candidates": stronger,
        "baseline_trendfollowing_candidates": baseline,
        "final_selected_candidate": final_selected,
        "smoke_decision": {
            "run_paper_smoke": classification == CLASS_FOUND and final_selected is not None,
            "reason": (
                "top stronger candidate passes full promotion contract"
                if classification == CLASS_FOUND and final_selected is not None
                else "no stronger runtime-compatible candidate passed promotion contract"
            ),
        },
    }
    return report


def render_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Runtime Compatible Stronger Alpha Discovery",
        "",
        f"- classification: `{report.get('classification')}`",
        f"- source_required: `{(report.get('scope') or {}).get('source_required')}`",
        f"- db_count: `{summary.get('db_count')}`",
        f"- runtime_events_scanned: `{summary.get('runtime_events_scanned')}`",
        f"- unique_candidate_count: `{summary.get('unique_candidate_count')}`",
        f"- promotion_contract_pass_count: `{summary.get('promotion_contract_pass_count')}`",
        f"- final_selected_candidate: `{(report.get('final_selected_candidate') or {}).get('candidate_key')}`",
        "",
        "## Threshold Buckets",
        f"- candidates_above_0_05: `{summary.get('candidates_above_0_05')}`",
        f"- candidates_above_0_08: `{summary.get('candidates_above_0_08')}`",
        f"- candidates_above_0_10: `{summary.get('candidates_above_0_10')}`",
        f"- candidates_above_0_12: `{summary.get('candidates_above_0_12')}`",
        "",
        "## Best Candidate Per Family",
    ]
    for family, candidate in (summary.get("best_candidate_per_family") or {}).items():
        lines.append(
            "- `{family}` `{key}` expected=`{expected}` class=`{classification}`".format(
                family=family,
                key=candidate.get("candidate_key"),
                expected=candidate.get("expected_net_after_full_cost"),
                classification=candidate.get("runtime_admissibility_classification"),
            )
        )
    lines.extend(["", "## Top 20 By Expected Net", ""])
    for candidate in report.get("top_20_by_expected_net_after_full_cost", [])[:20]:
        lines.append(
            "- `{key}` family=`{family}` expected=`{expected}` ratio=`{ratio}` admissible=`{admissible}` class=`{classification}`".format(
                key=candidate.get("candidate_key"),
                family=candidate.get("canonical_strategy"),
                expected=candidate.get("expected_net_after_full_cost"),
                ratio=candidate.get("entry_net_to_stop_ratio"),
                admissible=candidate.get("runtime_admissible"),
                classification=candidate.get("runtime_admissibility_classification"),
            )
        )
    return "\n".join(lines).strip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-report", type=Path, default=DEFAULT_RUNTIME_REPORT)
    parser.add_argument(
        "--output-json",
        type=Path,
        default=ANALYSIS_DIR / "runtime_compatible_stronger_alpha_current.json",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=ANALYSIS_DIR / "runtime_compatible_stronger_alpha_current.md",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = discover_from_runtime_report(args.runtime_report)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    args.output_md.write_text(render_markdown(report), encoding="utf-8")
    print(report["classification"])
    print(args.output_json)
    print(args.output_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
