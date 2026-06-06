from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from core.runtime_v2.contracts import EntryCandidate, QuoteTick


RUNTIME_SOURCE = "rolling_quote_window"
DEFAULT_HORIZONS = (1, 3, 5, 10)
CONTAMINATION_KEYS = ("seed", "fallback", "mock", "force_open", "forced_cycle")


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


def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        if value is None:
            return float(default) if default is not None else None
        return float(value)
    except (TypeError, ValueError):
        return float(default) if default is not None else None


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _clean_contamination(contamination_flags: dict[str, Any] | None) -> bool:
    flags = contamination_flags or {}
    for key in CONTAMINATION_KEYS:
        value = flags.get(key, 0)
        if value is True:
            return False
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value != 0:
            return False
        if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}:
            return False
    return True


@dataclass
class _TrackedCandidate:
    candidate: EntryCandidate
    reason_code: str
    contamination_flags: dict[str, Any]
    start_mid: float
    start_ts_ms: int
    pending_horizons: set[int]
    observed_ticks: int = 0
    emitted_horizons: set[int] = field(default_factory=set)


class PostSignalTrajectoryTracker:
    def __init__(self, horizons: Iterable[int] = DEFAULT_HORIZONS):
        self.horizons = tuple(sorted({int(h) for h in horizons if int(h) > 0}))
        self._tracked: dict[str, list[_TrackedCandidate]] = {}

    def observe_candidates(
        self,
        *,
        symbol: str,
        candidates: list[EntryCandidate],
        reason_code: str,
        contamination_flags: dict[str, Any] | None = None,
    ) -> None:
        if not _clean_contamination(contamination_flags):
            return
        for candidate in candidates[:3]:
            source = str(candidate.feature.profile_source or "")
            if source != RUNTIME_SOURCE:
                continue
            cost_source = str(candidate.cost_breakdown.get("runtime_profile_source") or source)
            if cost_source != RUNTIME_SOURCE:
                continue
            signal_horizon = _safe_int(candidate.signal_metadata.get("signal_horizon_ticks"))
            horizons = set(self.horizons)
            if signal_horizon and signal_horizon > 0:
                horizons.add(signal_horizon)
            tracked = _TrackedCandidate(
                candidate=candidate,
                reason_code=str(reason_code),
                contamination_flags={key: int((contamination_flags or {}).get(key, 0) or 0) for key in CONTAMINATION_KEYS},
                start_mid=float(candidate.quote.mid),
                start_ts_ms=int(candidate.quote.ts_ms),
                pending_horizons=horizons,
            )
            self._tracked.setdefault(str(symbol), []).append(tracked)

    def observe_quote(self, quote: QuoteTick) -> list[dict[str, Any]]:
        tracked_for_symbol = self._tracked.get(str(quote.symbol), [])
        if not tracked_for_symbol:
            return []
        emitted: list[dict[str, Any]] = []
        still_pending: list[_TrackedCandidate] = []
        for tracked in tracked_for_symbol:
            tracked.observed_ticks += 1
            due_horizons = sorted(
                horizon
                for horizon in tracked.pending_horizons
                if tracked.observed_ticks >= horizon and horizon not in tracked.emitted_horizons
            )
            for horizon in due_horizons:
                emitted.append(self._build_event(tracked, quote, horizon))
                tracked.emitted_horizons.add(horizon)
            if tracked.pending_horizons - tracked.emitted_horizons:
                still_pending.append(tracked)
        if still_pending:
            self._tracked[str(quote.symbol)] = still_pending
        else:
            self._tracked.pop(str(quote.symbol), None)
        return emitted

    def _build_event(
        self,
        tracked: _TrackedCandidate,
        quote: QuoteTick,
        horizon: int,
    ) -> dict[str, Any]:
        candidate = tracked.candidate
        start_mid = max(1e-12, tracked.start_mid)
        raw_move = (float(quote.mid) - start_mid) / start_mid
        signed_gross_move = raw_move if candidate.side == "buy" else -raw_move
        estimated_cost = _estimated_cost(candidate)
        signed_net_move = signed_gross_move - estimated_cost
        return {
            "symbol": candidate.symbol,
            "strategy": candidate.strategy,
            "canonical_strategy": canonical_strategy(candidate.strategy),
            "side": candidate.side,
            "source": RUNTIME_SOURCE,
            "profile_source": candidate.feature.profile_source,
            "runtime_profile_key": candidate.cost_breakdown.get("runtime_profile_key"),
            "runtime_profile_age_sec": candidate.feature.profile_age_sec,
            "runtime_profile_span_sec": candidate.feature.profile_span_sec,
            "runtime_profile_sample_size": candidate.feature.sample_count,
            "candidate_ts_ms": tracked.start_ts_ms,
            "quote_ts_ms": int(quote.ts_ms),
            "quote_window_timestamp_ms": int(quote.ts_ms),
            "horizon_ticks": int(horizon),
            "signed_gross_move": round(float(signed_gross_move), 12),
            "estimated_cost": round(float(estimated_cost), 12),
            "signed_net_move": round(float(signed_net_move), 12),
            "expected_move": float(candidate.expected_move),
            "expected_edge_after_fee": float(candidate.expected_edge_after_fee),
            "expected_net_after_cost": float(candidate.expected_net_after_cost),
            "expected_gross_before_cost": _safe_float(
                candidate.signal_metadata.get("expected_gross_before_cost"),
                _safe_float(candidate.cost_breakdown.get("expected_gross_before_cost"), candidate.expected_move),
            ),
            "expected_move_raw": _safe_float(
                candidate.signal_metadata.get("expected_move_raw"),
                candidate.expected_move,
            ),
            "expected_move_scaled": _safe_float(
                candidate.signal_metadata.get("expected_move_scaled"),
                candidate.expected_move,
            ),
            "signal_horizon_ticks": _safe_int(candidate.signal_metadata.get("signal_horizon_ticks")),
            "reason_code": tracked.reason_code,
            "contamination_flags": dict(tracked.contamination_flags),
        }


def _estimated_cost(candidate: EntryCandidate) -> float:
    breakdown = candidate.cost_breakdown or {}
    total = _safe_float(breakdown.get("total_cost_ratio"), None)  # type: ignore[arg-type]
    if total is not None:
        return float(total)
    return (
        _safe_float(breakdown.get("fee_round_trip_ratio"))
        + _safe_float(breakdown.get("spread_ratio"))
        + _safe_float(breakdown.get("slippage_ratio"))
    )
