from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def load_scorecard(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists() or path.stat().st_size <= 0:
        return None
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def assess_trading_metrics(scorecard: dict[str, Any] | None) -> dict[str, Any]:
    if not scorecard:
        return {
            "profitability_ready": False,
            "blockers": ["FRESH_SCORECARD_MISSING"],
            "live_ready": False,
        }

    blockers: list[str] = []
    metadata = scorecard.get("metadata") or {}
    scope = metadata.get("scope") or {}
    validation = metadata.get("validation") or {}
    kpis = scorecard.get("global_kpis") or {}
    contract = kpis.get("strategy_validation_contract") or {}
    natural = kpis.get("natural_entry_metrics") or {}

    if scope.get("exchange") != "KuCoin":
        blockers.append("SCOPE_NOT_KUCOIN")
    if scope.get("mode") != "PAPER_ONLY" or scope.get("live_in_scope") is not False:
        blockers.append("SCOPE_NOT_PAPER_ONLY")
    if validation.get("all_passed") is not True:
        blockers.append("CORPUS_VALIDATION_FAILED")
    if contract.get("usable_strategy_economics") is not True:
        blockers.append("NATURAL_SAMPLE_INSUFFICIENT")
    if int(contract.get("natural_entry_trade_count") or 0) < 60:
        blockers.append("NATURAL_TRADES_BELOW_60")
    if int(contract.get("assisted_entry_trade_count") or 0) != 0:
        blockers.append("ASSISTED_TRADES_PRESENT")
    if int(contract.get("unknown_entry_trade_count") or 0) != 0:
        blockers.append("UNKNOWN_TRADES_PRESENT")
    if natural.get("expectancy") is None or float(natural.get("expectancy") or 0) <= 0:
        blockers.append("EXPECTANCY_NOT_POSITIVE")
    if float(kpis.get("profitable_run_rate") or 0) < 0.70:
        blockers.append("PROFITABLE_RUN_RATE_BELOW_70_PERCENT")
    if float(kpis.get("pf_gt_1_rate") or 0) < 0.70:
        blockers.append("PF_GT_1_RATE_BELOW_70_PERCENT")

    oos = scorecard.get("out_of_sample") or {}
    if not oos:
        blockers.append("OOS_EVIDENCE_MISSING")
    elif float(oos.get("profit_factor") or 0) < 1.15:
        blockers.append("OOS_PROFIT_FACTOR_BELOW_1_15")

    if float(scorecard.get("positive_selected_cohorts_share") or 0) < 0.75:
        blockers.append("POSITIVE_COHORT_SHARE_BELOW_75_PERCENT")
    never_green = scorecard.get("never_green_share")
    if never_green is None:
        blockers.append("NEVER_GREEN_SHARE_MISSING")
    elif float(never_green) >= 0.20:
        blockers.append("NEVER_GREEN_SHARE_NOT_BELOW_20_PERCENT")

    weekly = scorecard.get("weekly_windows") or []
    if len(weekly) < 4 or any(float(item.get("net_pnl") or 0) <= 0 for item in weekly[-4:]):
        blockers.append("FOUR_POSITIVE_PAPER_WEEKS_MISSING")

    generated_at = metadata.get("generated_at")
    try:
        generated = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - generated > timedelta(days=7):
            blockers.append("SCORECARD_STALE")
    except Exception:
        blockers.append("SCORECARD_TIMESTAMP_INVALID")

    return {
        "profitability_ready": not blockers,
        "blockers": sorted(set(blockers)),
        "live_ready": False,
        "live_policy": "separate operational gate and explicit human approval required",
    }
