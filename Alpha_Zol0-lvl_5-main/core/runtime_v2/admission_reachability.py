from __future__ import annotations

import os
from typing import Any, Dict


PROFILE_ENV_KEY = "V2_PAPER_ADMISSION_REACHABILITY_PROFILE_ENABLE"
PROFILE_SOURCE = PROFILE_ENV_KEY
RELAXED_V2_MIN_EXPECTED_NET_RATIO = 0.00002
RELAXED_ENTRY_MIN_NET_USDT = 0.02
RELAXED_V2_MIN_PROFILE_SAMPLES = 4


def _env_flag(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _live_enabled() -> bool:
    return _env_flag("LIVE", False)


def paper_admission_reachability_profile_requested() -> bool:
    return _env_flag(PROFILE_ENV_KEY, False)


def paper_admission_reachability_profile_enabled() -> bool:
    return paper_admission_reachability_profile_requested() and not _live_enabled()


def paper_admission_reachability_live_override_blocked() -> bool:
    return paper_admission_reachability_profile_requested() and _live_enabled()


def effective_v2_min_expected_net_ratio(default_value: float) -> float:
    if paper_admission_reachability_profile_enabled():
        return float(RELAXED_V2_MIN_EXPECTED_NET_RATIO)
    return float(default_value)


def effective_entry_min_net_usdt(default_value: float) -> float:
    if paper_admission_reachability_profile_enabled():
        return float(RELAXED_ENTRY_MIN_NET_USDT)
    return float(default_value)


def effective_v2_min_profile_samples(default_value: int) -> int:
    if paper_admission_reachability_profile_enabled():
        return int(RELAXED_V2_MIN_PROFILE_SAMPLES)
    return int(default_value)


def admission_reachability_profile_payload(
    *,
    default_v2_min_expected_net_ratio: float,
    default_entry_min_net_usdt: float,
    default_v2_min_profile_samples: int,
) -> Dict[str, Any]:
    enabled = paper_admission_reachability_profile_enabled()
    return {
        "paper_admission_reachability_profile_enabled": bool(enabled),
        "paper_admission_reachability_profile_source": PROFILE_SOURCE,
        "effective_v2_min_expected_net_ratio": effective_v2_min_expected_net_ratio(
            default_v2_min_expected_net_ratio
        ),
        "effective_entry_min_net_usdt": effective_entry_min_net_usdt(
            default_entry_min_net_usdt
        ),
        "effective_v2_min_profile_samples": effective_v2_min_profile_samples(
            default_v2_min_profile_samples
        ),
        "default_thresholds_preserved": not bool(enabled),
        "live_override_blocked": paper_admission_reachability_live_override_blocked(),
    }
