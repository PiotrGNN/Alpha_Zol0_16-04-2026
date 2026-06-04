from __future__ import annotations

import math
from collections import defaultdict, deque
from typing import Deque, Dict, Iterable, List, Optional, Tuple

from core.runtime_v2.contracts import (
    EntryCandidate,
    FeatureFrame,
    QuoteTick,
    StrategySignal,
)


def _as_float_env(env_key: str, default: float) -> float:
    import os

    try:
        return float(os.environ.get(env_key, str(default)))
    except Exception:
        return float(default)


def _as_bool_env(env_key: str, default: bool) -> bool:
    import os

    raw = str(os.environ.get(env_key, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _safe_float(value, default: float) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


class DecisionEngineV2:
    def __init__(self):
        self.fee_rate = max(0.0, _as_float_env("PAPER_FEE_RATE", 0.0001))
        self.slippage_bps = max(0.0, _as_float_env("V2_SLIPPAGE_BPS", 0.25))
        self.spread_cost_mult = max(0.0, _as_float_env("V2_SPREAD_COST_MULT", 0.10))
        self.min_probability = max(0.0, _as_float_env("V2_MIN_PROBABILITY", 0.52))
        self.min_expected_net_ratio = _as_float_env("V2_MIN_EXPECTED_NET_RATIO", 0.0006)
        self.profile_quality_fail_closed = _as_bool_env(
            "V2_PROFILE_QUALITY_FAIL_CLOSED", False
        )
        self.profile_min_sample = max(
            1,
            int(_as_float_env("V2_PROFILE_MIN_SAMPLE", 12)),
        )
        self.profile_min_age_sec = max(
            0.0,
            _as_float_env("V2_PROFILE_MIN_AGE_SEC", 15.0),
        )
        self.profile_min_span_sec = max(
            0.0, _as_float_env("V2_PROFILE_MIN_SPAN_SEC", 10.0)
        )
        self.fail_closed_after_first_loss = _as_bool_env(
            "V2_FAIL_CLOSED_AFTER_FIRST_LOSS", False
        )
        self.throttle_min_trades = max(
            1,
            int(_as_float_env("V2_THROTTLE_MIN_TRADES", 2)),
        )
        self.side_guard_min_trades = max(
            1,
            int(_as_float_env("V2_SIDE_GUARD_MIN_TRADES", 3)),
        )
        self.side_guard_min_winrate = max(
            0.0,
            _as_float_env("V2_SIDE_GUARD_MIN_WINRATE", 0.45),
        )
        self.side_expectancy_min = _as_float_env("V2_SIDE_EXPECTANCY_MIN", 0.0)
        self.allow_no_runtime_profile = _as_bool_env(
            "V2_ALLOW_NO_RUNTIME_PROFILE", False
        )
        self.diagnostic_force_open = _as_bool_env(
            "ENTRY_ALLOWLIST_DIAGNOSTIC_FORCE_OPEN", False
        )
        self._bucket_pnl: Dict[Tuple[str, str, str], Deque[float]] = defaultdict(
            lambda: deque(maxlen=60)
        )
        self._bucket_wins: Dict[Tuple[str, str, str], Deque[int]] = defaultdict(
            lambda: deque(maxlen=60)
        )

    def _symbol_trade_count(self, symbol: str) -> int:
        symbol_key = str(symbol).upper()
        total = 0
        for (bucket_symbol, _strategy, _side), pnl_series in self._bucket_pnl.items():
            if bucket_symbol == symbol_key:
                total += len(pnl_series)
        return int(total)

    def register_trade_result(
        self,
        *,
        symbol: str,
        strategy: str,
        side: str,
        net_pnl: float,
    ) -> None:
        key = (str(symbol).upper(), str(strategy), str(side).lower())
        self._bucket_pnl[key].append(float(net_pnl))
        self._bucket_wins[key].append(1 if float(net_pnl) > 0 else 0)

    def _bucket_stats(self, symbol: str, strategy: str, side: str) -> Dict[str, float]:
        key = (str(symbol).upper(), str(strategy), str(side).lower())
        pnl_series = self._bucket_pnl[key]
        wins_series = self._bucket_wins[key]
        trades = len(pnl_series)
        expectancy = (sum(pnl_series) / trades) if trades > 0 else 0.0
        winrate = (sum(wins_series) / trades) if trades > 0 else 0.0
        return {
            "trade_count": float(trades),
            "expectancy": float(expectancy),
            "winrate": float(winrate),
        }

    def _cost_breakdown(self, quote: QuoteTick) -> Dict[str, float]:
        fee_round_trip = max(0.0, float(self.fee_rate) * 2.0)
        spread_ratio = (
            float(quote.spread_abs) / float(quote.mid)
            if quote.mid > 0
            else 0.0
        )
        spread_ratio *= self.spread_cost_mult
        slippage_ratio = max(0.0, float(self.slippage_bps) / 10_000.0) * 2.0
        total = fee_round_trip + spread_ratio + slippage_ratio
        return {
            "fee_rate": float(self.fee_rate),
            "fee_round_trip_ratio": fee_round_trip,
            "spread_ratio": spread_ratio,
            "slippage_ratio": slippage_ratio,
            "total_cost_ratio": total,
        }

    def _probability_of_profit(
        self,
        expected_net_ratio: float,
        volatility: float,
    ) -> float:
        vol = max(1e-8, float(volatility))
        z = expected_net_ratio / vol
        p = 1.0 / (1.0 + math.exp(-4.0 * z))
        if p < 0.0:
            return 0.0
        if p > 1.0:
            return 1.0
        return p

    def evaluate(
        self,
        *,
        quote: QuoteTick,
        feature: FeatureFrame,
        signals: Iterable[StrategySignal],
    ) -> Tuple[List[EntryCandidate], Optional[EntryCandidate], str]:
        if (
            not feature.has_profile
            and not self.diagnostic_force_open
            and not self.allow_no_runtime_profile
        ):
            return [], None, "no_runtime_profile"
        if self.profile_quality_fail_closed:
            if int(feature.sample_count) < self.profile_min_sample:
                return [], None, "runtime_profile_quality_fail_closed"
            if float(feature.profile_age_sec) < self.profile_min_age_sec:
                return [], None, "runtime_profile_quality_fail_closed"
            if float(feature.profile_span_sec) < self.profile_min_span_sec:
                return [], None, "runtime_profile_quality_fail_closed"

        candidates: List[EntryCandidate] = []
        costs = self._cost_breakdown(quote)
        for signal in signals:
            if signal.direction not in ("buy", "sell"):
                continue
            expected_move = max(0.0, float(signal.expected_move))
            expected_edge_after_fee = expected_move - costs["fee_round_trip_ratio"]
            expected_net_after_cost = expected_move - costs["total_cost_ratio"]
            probability = self._probability_of_profit(
                expected_net_after_cost, feature.volatility
            )
            stats = self._bucket_stats(quote.symbol, signal.strategy, signal.direction)
            symbol_trade_count = self._symbol_trade_count(quote.symbol)
            tuple_trade_count = int(stats["trade_count"])
            tuple_concentration = (
                float(tuple_trade_count / symbol_trade_count)
                if symbol_trade_count > 0
                else 0.0
            )
            signal_metadata = dict(signal.metadata or {})
            expected_move_raw = max(
                0.0,
                _safe_float(signal_metadata.get("expected_move_raw"), expected_move),
            )
            expected_move_scaled = max(
                0.0,
                _safe_float(signal_metadata.get("expected_move_scaled"), expected_move),
            )
            signal_metadata["expected_move_raw"] = expected_move_raw
            signal_metadata["expected_move_scaled"] = expected_move_scaled
            signal_metadata["expected_gross_before_cost"] = expected_move_scaled
            signal_horizon_ticks = signal_metadata.get("signal_horizon_ticks", 1.0)
            try:
                signal_horizon_ticks = float(signal_horizon_ticks)
            except Exception:
                signal_horizon_ticks = 1.0
            runtime_profile_key = (
                f"{quote.symbol}|"
                f"{feature.profile_source}|"
                f"n={int(feature.sample_count)}|"
                f"span={int(feature.profile_span_sec)}"
            )
            candidate = EntryCandidate(
                symbol=quote.symbol,
                side=signal.direction,
                strategy=signal.strategy,
                score=float(signal.score),
                confidence=float(signal.confidence),
                expected_move=expected_move,
                expected_edge_after_fee=expected_edge_after_fee,
                expected_net_after_cost=expected_net_after_cost,
                probability_of_profit=probability,
                quote=quote,
                feature=feature,
                reason_code=signal.reason_code,
                cost_breakdown={
                    **costs,
                    "bucket_trade_count": tuple_trade_count,
                    "bucket_expectancy": float(stats["expectancy"]),
                    "bucket_winrate": float(stats["winrate"]),
                    "symbol_trade_count": symbol_trade_count,
                    "tuple_concentration": tuple_concentration,
                    "trendfollowing_tuple_concentration": (
                        tuple_concentration
                        if str(signal.strategy) == "TrendFollowingV2"
                        else None
                    ),
                    "runtime_profile_source": str(feature.profile_source),
                    "runtime_profile_key": runtime_profile_key,
                    "runtime_profile_age_sec": float(feature.profile_age_sec),
                    "runtime_profile_span_sec": float(feature.profile_span_sec),
                    "runtime_profile_sample_size": int(feature.sample_count),
                    "expected_move_raw": expected_move_raw,
                    "expected_move_scaled": expected_move_scaled,
                    "expected_gross_before_cost": expected_move_scaled,
                    "signal_horizon_ticks": signal_horizon_ticks,
                },
                signal_metadata=signal_metadata,
            )
            candidates.append(candidate)

        if not candidates:
            if self.diagnostic_force_open:
                expected_move = max(
                    float(costs["total_cost_ratio"])
                    + float(self.min_expected_net_ratio),
                    float(self.min_expected_net_ratio) * 1.25,
                )
                expected_edge_after_fee = (
                    expected_move - float(costs["fee_round_trip_ratio"])
                )
                expected_net_after_cost = (
                    expected_move - float(costs["total_cost_ratio"])
                )
                runtime_profile_key = (
                    f"{quote.symbol}|{feature.profile_source}|"
                    f"n={int(feature.sample_count)}|"
                    f"span={int(feature.profile_span_sec)}"
                )
                fallback = EntryCandidate(
                    symbol=quote.symbol,
                    side="buy",
                    strategy="DiagnosticForceOpenV2",
                    score=0.51,
                    confidence=0.51,
                    expected_move=expected_move,
                    expected_edge_after_fee=expected_edge_after_fee,
                    expected_net_after_cost=expected_net_after_cost,
                    probability_of_profit=0.51,
                    quote=quote,
                    feature=feature,
                    reason_code="diagnostic_force_open_no_edge",
                    cost_breakdown={
                        **costs,
                        "bucket_trade_count": 0,
                        "bucket_expectancy": 0.0,
                        "bucket_winrate": 0.0,
                        "symbol_trade_count": self._symbol_trade_count(quote.symbol),
                        "tuple_concentration": 0.0,
                        "trendfollowing_tuple_concentration": None,
                        "runtime_profile_source": str(feature.profile_source),
                        "runtime_profile_key": runtime_profile_key,
                        "runtime_profile_age_sec": float(feature.profile_age_sec),
                        "runtime_profile_span_sec": float(feature.profile_span_sec),
                        "runtime_profile_sample_size": int(feature.sample_count),
                        "expected_move_raw": expected_move,
                        "expected_move_scaled": expected_move,
                        "expected_gross_before_cost": expected_move,
                        "signal_horizon_ticks": 1.0,
                    },
                    signal_metadata={
                        "diagnostic_force_open": True,
                        "fallback_reason": "no_edge",
                    },
                )
                candidates = [fallback]
            else:
                return [], None, "no_edge"

        filtered: List[EntryCandidate] = []
        tuple_first_loss_blocked = False
        side_expectancy_blocked = False
        side_guard_blocked = False
        for candidate in candidates:
            if self.diagnostic_force_open:
                filtered.append(candidate)
                continue
            stats = candidate.cost_breakdown
            bucket_trade_count = int(stats.get("bucket_trade_count", 0))
            bucket_expectancy = float(stats.get("bucket_expectancy", 0.0))
            bucket_winrate = float(stats.get("bucket_winrate", 0.0))
            if (
                self.fail_closed_after_first_loss
                and bucket_trade_count >= 1
                and bucket_expectancy < 0.0
            ):
                tuple_first_loss_blocked = True
                continue
            if (
                bucket_trade_count >= self.throttle_min_trades
                and bucket_expectancy <= self.side_expectancy_min
            ):
                side_expectancy_blocked = True
                continue
            if (
                bucket_trade_count >= self.side_guard_min_trades
                and bucket_winrate < self.side_guard_min_winrate
            ):
                side_guard_blocked = True
                continue
            if candidate.expected_net_after_cost <= self.min_expected_net_ratio:
                continue
            if candidate.probability_of_profit < self.min_probability:
                continue
            filtered.append(candidate)

        if not filtered:
            if tuple_first_loss_blocked:
                return candidates, None, "tuple_first_loss_penalty"
            if side_expectancy_blocked:
                return candidates, None, "side_expectancy"
            if side_guard_blocked:
                return candidates, None, "side_guard"
            return candidates, None, "entry_edge_filtered"

        filtered.sort(
            key=lambda item: (
                item.expected_net_after_cost * item.confidence,
                item.probability_of_profit,
                item.score,
            ),
            reverse=True,
        )
        return candidates, filtered[0], "allow"
