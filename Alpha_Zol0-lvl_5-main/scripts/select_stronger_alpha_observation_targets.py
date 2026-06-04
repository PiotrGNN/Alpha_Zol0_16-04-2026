from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


WORKDIR = Path(__file__).resolve().parents[1]
RUNTIME_SOURCE = "rolling_quote_window"
STRONGER_FAMILIES = {"MICROBREAKOUT", "MOMENTUM", "MEANREVERSION"}
BASELINE_FAMILIES = {"TRENDFOLLOWING"}

CLASS_TARGETS_SELECTED = "STRONGER_ALPHA_OBSERVATION_TARGETS_SELECTED"
CLASS_BLOCKED_UNIT_MISMATCH = "STRONGER_ALPHA_SEARCH_BLOCKED_BY_UNIT_SANITY"
CLASS_BLOCKED_NO_CLEAN_NON_TREND = "STRONGER_ALPHA_SEARCH_BLOCKED_BY_NO_CLEAN_NON_TREND_EVIDENCE"

FAMILY_PRIORITY = {
    "MICROBREAKOUT": 1,
    "MOMENTUM": 2,
    "MEANREVERSION": 3,
    "TRENDFOLLOWING": 4,
}

PAPER_ENV = {
    "LIVE": "0",
    "USE_MOCK": "0",
    "ENGINE_VERSION": "v2",
    "RUNTIME_V2_POST_SIGNAL_TRAJECTORY": "1",
    "SEED_TRADES_ENABLE": "0",
    "ALPHA_WHITELIST_FALLBACK_ENABLE": "0",
    "ENTRY_ALLOWLIST_DIAGNOSTIC_FORCE_OPEN": "0",
    "PAPER_AUTO_OPEN_REQUIRE_EXPLICIT_SIDE_ALLOWLIST": "0",
}


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_strategy(strategy: Any) -> str:
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


def _contaminated(row: dict[str, Any]) -> bool:
    if bool(row.get("contaminated")):
        return True
    flags = row.get("contamination_flags")
    if isinstance(flags, dict):
        return any(bool(flags.get(key)) for key in ("seed", "fallback", "mock", "force_open", "forced_cycle"))
    counts = row.get("contamination_counts")
    if isinstance(counts, dict):
        return any((_safe_float(counts.get(key)) or 0.0) > 0.0 for key in ("seed", "fallback", "mock", "force_open", "forced_cycle"))
    return False


def _candidate_key(symbol: Any, strategy: Any, side: Any) -> str:
    return f"{str(symbol or '').upper()}:{_canonical_strategy(strategy)}:{str(side or '').lower()}"


def _env_for_target(target: dict[str, Any]) -> dict[str, str]:
    env = dict(PAPER_ENV)
    env["ENTRY_STRATEGY_ALLOWLIST"] = str(target["canonical_strategy"])
    env["ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST"] = target["candidate_key"]
    return env


def _from_post_signal_failure(failure: dict[str, Any]) -> list[dict[str, Any]]:
    rows = failure.get("best_20_trajectory_events_by_net_opportunity") or failure.get("best_events_by_net_opportunity") or []
    targets: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return targets
    for row in rows:
        if not isinstance(row, dict):
            continue
        canonical = _canonical_strategy(row.get("canonical_strategy") or row.get("strategy"))
        if canonical not in STRONGER_FAMILIES:
            continue
        if str(row.get("source") or "") != RUNTIME_SOURCE:
            continue
        if _contaminated(row):
            continue
        symbol = str(row.get("symbol") or "").upper()
        side = str(row.get("side") or "").lower()
        if not symbol or side not in {"buy", "sell"}:
            continue
        target = {
            "candidate_key": _candidate_key(symbol, canonical, side),
            "symbol": symbol,
            "canonical_strategy": canonical,
            "strategy": row.get("strategy") or canonical,
            "side": side,
            "source": RUNTIME_SOURCE,
            "evidence_source": "post_signal_alpha_target_failure",
            "horizon_ticks": row.get("horizon_ticks"),
            "signed_net_move": _safe_float(row.get("signed_net_move")),
            "mfe": _safe_float(row.get("mfe")),
            "estimated_cost": _safe_float(row.get("estimated_cost")),
            "expected_net_after_full_cost": None,
            "runtime_admissibility_classification": None,
            "telemetry_gap_fields": [],
            "reason_code": row.get("reason_code"),
        }
        target["paper_validation_env"] = _env_for_target(target)
        targets.append(target)
    return targets


def _from_stronger_discovery(stronger: dict[str, Any]) -> list[dict[str, Any]]:
    best = ((stronger.get("summary") or {}).get("best_candidate_per_family") or {})
    targets: list[dict[str, Any]] = []
    if not isinstance(best, dict):
        return targets
    for row in best.values():
        if not isinstance(row, dict):
            continue
        canonical = _canonical_strategy(row.get("canonical_strategy") or row.get("strategy"))
        if canonical not in STRONGER_FAMILIES:
            continue
        if str(row.get("source") or row.get("profile_source") or "") != RUNTIME_SOURCE:
            continue
        if _contaminated(row):
            continue
        symbol = str(row.get("symbol") or "").upper()
        side = str(row.get("side") or "").lower()
        if not symbol or side not in {"buy", "sell"}:
            continue
        target = {
            "candidate_key": _candidate_key(symbol, canonical, side),
            "symbol": symbol,
            "canonical_strategy": canonical,
            "strategy": row.get("strategy") or canonical,
            "side": side,
            "source": RUNTIME_SOURCE,
            "evidence_source": "runtime_compatible_stronger_alpha",
            "horizon_ticks": None,
            "signed_net_move": None,
            "mfe": None,
            "estimated_cost": None,
            "expected_net_after_full_cost": _safe_float(row.get("expected_net_after_full_cost")),
            "runtime_admissibility_classification": row.get("runtime_admissibility_classification"),
            "telemetry_gap_fields": row.get("telemetry_gap_fields") if isinstance(row.get("telemetry_gap_fields"), list) else [],
            "reason_code": None,
        }
        target["paper_validation_env"] = _env_for_target(target)
        targets.append(target)
    return targets


def _dedupe_and_rank(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for target in targets:
        key = target["candidate_key"]
        current = by_key.get(key)
        if current is None:
            by_key[key] = target
            continue
        current_net = _safe_float(current.get("signed_net_move")) or -999.0
        new_net = _safe_float(target.get("signed_net_move")) or -999.0
        current_expected = _safe_float(current.get("expected_net_after_full_cost")) or -999.0
        new_expected = _safe_float(target.get("expected_net_after_full_cost")) or -999.0
        if (new_net, new_expected) > (current_net, current_expected):
            by_key[key] = target
    ranked = list(by_key.values())
    ranked.sort(
        key=lambda target: (
            FAMILY_PRIORITY.get(str(target.get("canonical_strategy")), 99),
            -(_safe_float(target.get("signed_net_move")) or -999.0),
            -(_safe_float(target.get("expected_net_after_full_cost")) or -999.0),
            str(target.get("candidate_key")),
        )
    )
    for rank, target in enumerate(ranked, start=1):
        target["rank"] = rank
    return ranked


def select_observation_targets(
    unit_sanity_artifact: Path | str,
    search_plan_artifact: Path | str,
    failure_artifact: Path | str,
    stronger_artifact: Path | str,
    *,
    max_targets: int = 6,
) -> dict[str, Any]:
    unit = _read_json(Path(unit_sanity_artifact))
    plan = _read_json(Path(search_plan_artifact))
    failure = _read_json(Path(failure_artifact))
    stronger = _read_json(Path(stronger_artifact))
    if unit.get("classification") != "POST_SIGNAL_ALPHA_TARGET_UNITS_CONSISTENT":
        classification = CLASS_BLOCKED_UNIT_MISMATCH
        selected: list[dict[str, Any]] = []
    else:
        selected = _dedupe_and_rank(_from_post_signal_failure(failure) + _from_stronger_discovery(stronger))[:max_targets]
        classification = CLASS_TARGETS_SELECTED if selected else CLASS_BLOCKED_NO_CLEAN_NON_TREND
    return {
        "classification": classification,
        "inputs": {
            "unit_sanity_artifact": str(unit_sanity_artifact),
            "search_plan_artifact": str(search_plan_artifact),
            "failure_artifact": str(failure_artifact),
            "stronger_artifact": str(stronger_artifact),
            "max_targets": int(max_targets),
        },
        "summary": {
            "unit_sanity_classification": unit.get("classification"),
            "search_plan_classification": plan.get("classification"),
            "failure_classification": failure.get("classification"),
            "stronger_alpha_classification": stronger.get("classification"),
            "selected_target_count": len(selected),
        },
        "selected_targets": selected,
        "baseline_families": sorted(BASELINE_FAMILIES),
        "profitability_claim": False,
        "next_action": _next_action(classification, selected),
    }


def _next_action(classification: str, selected: list[dict[str, Any]]) -> dict[str, Any]:
    if classification != CLASS_TARGETS_SELECTED:
        return {
            "action": "fail_closed",
            "reason": "no clean non-TrendFollowing PAPER observation target selected",
        }
    return {
        "action": "run_paper_observation",
        "first_target": selected[0]["candidate_key"],
        "required_runtime_flags": dict(selected[0]["paper_validation_env"]),
        "forbidden": [
            "LIVE",
            "USE_MOCK=1",
            "seed",
            "fallback",
            "diagnostic_force_open",
            "threshold_patch",
            "strategy_patch",
            "readiness_patch",
            "execution_patch",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Stronger Alpha Observation Targets",
        "",
        f"- classification: `{report['classification']}`",
        f"- selected_target_count: `{report['summary']['selected_target_count']}`",
        f"- unit_sanity_classification: `{report['summary']['unit_sanity_classification']}`",
        f"- profitability_claim: `{report['profitability_claim']}`",
        "",
        "## Selected Targets",
    ]
    if not report["selected_targets"]:
        lines.append("- none")
    for target in report["selected_targets"]:
        lines.append(
            "- rank=`{rank}` `{key}` source=`{source}` net=`{net}` expected_full=`{expected}` class=`{classification}`".format(
                rank=target["rank"],
                key=target["candidate_key"],
                source=target["evidence_source"],
                net=target.get("signed_net_move"),
                expected=target.get("expected_net_after_full_cost"),
                classification=target.get("runtime_admissibility_classification"),
            )
        )
    lines.extend(
        [
            "",
            "## Next Action",
            f"- action: `{report['next_action']['action']}`",
            f"- first_target: `{report['next_action'].get('first_target')}`",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit-sanity-artifact", default="analysis/post_signal_alpha_target_unit_sanity_current.json")
    parser.add_argument("--search-plan-artifact", default="analysis/stronger_alpha_search_plan_current.json")
    parser.add_argument("--failure-artifact", default="analysis/post_signal_alpha_target_failure_current.json")
    parser.add_argument("--stronger-artifact", default="analysis/runtime_compatible_stronger_alpha_current.json")
    parser.add_argument("--output-json", default="analysis/stronger_alpha_observation_targets_current.json")
    parser.add_argument("--output-md", default="analysis/stronger_alpha_observation_targets_current.md")
    parser.add_argument("--max-targets", type=int, default=6)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = select_observation_targets(
        WORKDIR / args.unit_sanity_artifact,
        WORKDIR / args.search_plan_artifact,
        WORKDIR / args.failure_artifact,
        WORKDIR / args.stronger_artifact,
        max_targets=args.max_targets,
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
