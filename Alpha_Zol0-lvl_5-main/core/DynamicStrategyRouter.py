"""
DynamicStrategyRouter: Ensemble & Regime-Switching for ZoL0 Level Ω
Dynamic allocation and switching between multiple strategies
based on market regime and performance.
"""

from typing import List, Dict, Any
import math
import os
from inspect import signature


class DynamicStrategyRouter:
    def get_status(self):
        return {
            "strategies": [getattr(s, "name", str(s)) for s in self.strategies],
            "last_allocations": getattr(self, "last_allocations", {}),
            "last_regime": getattr(self, "last_regime", None),
            "last_guarded_strategies": getattr(
                self, "last_guarded_strategies", {}
            ),
        }

    def __init__(
        self,
        strategies: List[Any],
        perf_tracker=None,
        risk_manager=None,
        meta_model=None,
    ):
        self.strategies = strategies
        self.perf_tracker = perf_tracker
        self.risk_manager = risk_manager
        self.meta_model = meta_model  # Optional AI regime classifier
        self.last_regime = None
        self.last_allocations = {s.name: 1.0 / len(strategies) for s in strategies}
        self.last_guarded_strategies = {}

    def detect_regime(self, market_state: Dict[str, Any]) -> str:
        # Example: rule-based regime detection
        def safe_float(val, default=0.0):
            # BotCore provides `trend` as a label ("UP"/"DOWN"/"SIDE").
            # Accept common string encodings so regime switching can work
            # without changing strategy inputs.
            if isinstance(val, str):
                v = val.strip().upper()
                if v in ("UP", "BULL", "LONG", "BUY", "↑"):
                    return 1.0
                if v in ("DOWN", "BEAR", "SHORT", "SELL", "↓"):
                    return -1.0
                if v in ("SIDE", "SIDEWAYS", "FLAT", "HOLD", "→"):
                    return 0.0
            try:
                return float(val)
            except (TypeError, ValueError):
                return default

        # If caller provided an explicit string trend that denotes "sideways",
        # respect that label regardless of numeric volatility. This preserves
        # behavior where string labels (e.g. coming from BotCore) should take
        # precedence for regime detection.
        trend_raw = market_state.get("trend")
        if isinstance(trend_raw, str) and trend_raw.strip().upper() in (
            "SIDE",
            "SIDEWAYS",
            "FLAT",
            "HOLD",
            "→",
        ):
            return "sideways"

        trend = safe_float(market_state.get("trend", 0))
        vol = safe_float(market_state.get("volatility", 0))
        sentiment = safe_float(market_state.get("sentiment", 0))
        try:
            trend_vol_min = float(os.environ.get("REGIME_TREND_VOL_MIN", "0.06"))
        except Exception:
            trend_vol_min = 0.06
        try:
            sideways_vol_max = float(os.environ.get("REGIME_SIDEWAYS_VOL_MAX", "0.03"))
        except Exception:
            sideways_vol_max = 0.03
        if abs(trend) > 0.7 and vol >= trend_vol_min:
            return "trend"
        elif vol <= sideways_vol_max:
            return "sideways"
        elif sentiment > 0.7:
            return "sentiment"
        else:
            return "mixed"

    def compute_allocations(
        self, regime: str, perf_stats: Dict[str, Any]
    ) -> Dict[str, float]:
        # Example: regime-based allocation logic
        alloc = {s.name: 0.0 for s in self.strategies}
        if regime == "trend":
            alloc["TrendFollowing"] = 0.50
            alloc["Momentum"] = 0.30
            alloc["MeanReversion"] = 0.20
        elif regime == "sideways":
            # Directional strategies only – GridTrading/MarketMaking are
            # non-directional and cancel buy/sell votes → removed.
            alloc["Momentum"] = 0.40
            alloc["TrendFollowing"] = 0.30
            alloc["MeanReversion"] = 0.30
        elif regime == "sentiment":
            alloc["Sentiment"] = 0.7
            alloc["Breakout"] = 0.2
            alloc["Arbitrage"] = 0.1
        else:
            # Mixed / unknown regime: allocate by recent Sharpe when available,
            # otherwise fall back to directional-heavy defaults (same as trend)
            # so non-directional strategies don't dilute buy/sell votes.
            sharpe = {k: v.get("sharpe", 0) for k, v in perf_stats.items()}
            total = sum(abs(x) for x in sharpe.values())
            if total > 0:
                for k in alloc:
                    alloc[k] = abs(sharpe.get(k, 0)) / total
            else:
                # No performance data yet → directional default
                alloc["TrendFollowing"] = 0.45
                alloc["Momentum"] = 0.35
                alloc["MeanReversion"] = 0.20
        if sum(alloc.values()) <= 0:
            # Ultimate fallback: directional trio
            alloc["TrendFollowing"] = 0.45
            alloc["Momentum"] = 0.35
            alloc["MeanReversion"] = 0.20
        guarded = {}
        try:
            guard_enabled = os.environ.get("STRATEGY_GUARD_ENABLE", "1") == "1"
        except Exception:
            guard_enabled = True
        if guard_enabled and perf_stats:
            try:
                min_trades = int(os.environ.get("STRATEGY_GUARD_MIN_TRADES", "6"))
            except Exception:
                min_trades = 6
            try:
                min_pf = float(os.environ.get("STRATEGY_GUARD_MIN_PF", "0.9"))
            except Exception:
                min_pf = 0.9
            try:
                min_wr = float(os.environ.get("STRATEGY_GUARD_MIN_WINRATE", "0.25"))
            except Exception:
                min_wr = 0.25
            try:
                max_dd = float(os.environ.get("STRATEGY_GUARD_MAX_DD", "0.25"))
            except Exception:
                max_dd = 0.25
            try:
                min_score = float(os.environ.get("STRATEGY_GUARD_MIN_SCORE", "-0.25"))
            except Exception:
                min_score = -0.25
            for name in list(alloc.keys()):
                stats = perf_stats.get(name) or {}
                try:
                    trades = int(stats.get("trade_count", 0) or 0)
                except Exception:
                    trades = 0
                if trades < min_trades:
                    continue
                try:
                    pf_val = float(stats.get("profit_factor", 0.0) or 0.0)
                except Exception:
                    pf_val = 0.0
                try:
                    wr_val = float(stats.get("winrate", 0.0) or 0.0)
                except Exception:
                    wr_val = 0.0
                try:
                    dd_val = float(stats.get("drawdown", 0.0) or 0.0)
                except Exception:
                    dd_val = 0.0
                try:
                    score_val = float(stats.get("score", 0.0) or 0.0)
                except Exception:
                    score_val = 0.0
                try:
                    pnl_val = float(stats.get("pnl", 0.0) or 0.0)
                except Exception:
                    pnl_val = 0.0
                is_bad = (
                    (pf_val < min_pf and wr_val < min_wr and pnl_val < 0)
                    or (dd_val > max_dd and pnl_val < 0)
                    or (score_val < min_score and pnl_val < 0)
                )
                if is_bad:
                    alloc[name] = 0.0
                    guarded[name] = {
                        "trades": trades,
                        "pnl": pnl_val,
                        "pf": pf_val,
                        "winrate": wr_val,
                        "drawdown": dd_val,
                        "score": score_val,
                    }
        # Allow disabling specific strategies via env
        try:
            disabled_raw = os.environ.get("DISABLE_STRATEGIES", "")
        except Exception:
            disabled_raw = ""
        disabled = {
            name.strip() for name in str(disabled_raw).split(",") if name.strip()
        }
        if disabled:
            for name in disabled:
                if name in alloc:
                    alloc[name] = 0.0
                    guarded[name] = {"reason": "DISABLE_STRATEGIES"}
            if sum(alloc.values()) <= 0:
                self.last_guarded_strategies = guarded
                self.last_allocations = alloc
                return alloc
        # Optional performance overlay (reward/penalty) to refine allocations
        try:
            reward_enabled = os.environ.get("STRATEGY_REWARD_ENABLE", "1") == "1"
        except Exception:
            reward_enabled = True
        try:
            live_mode = os.environ.get("LIVE", "0") == "1"
        except Exception:
            live_mode = False
        if reward_enabled and (not live_mode) and perf_stats:
            try:
                reward_metric = os.environ.get("STRATEGY_REWARD_METRIC", "score")
            except Exception:
                reward_metric = "score"
            try:
                reward_scale = float(os.environ.get("STRATEGY_REWARD_SCALE", "0.5"))
            except Exception:
                reward_scale = 0.5
            try:
                min_scale = float(os.environ.get("STRATEGY_REWARD_MIN", "0.25"))
            except Exception:
                min_scale = 0.25
            try:
                max_scale = float(os.environ.get("STRATEGY_REWARD_MAX", "1.75"))
            except Exception:
                max_scale = 1.75
            weighted = {}
            for name, weight in alloc.items():
                stats = perf_stats.get(name) or {}
                raw_val = stats.get(reward_metric)
                if raw_val is None:
                    raw_val = stats.get("score")
                if raw_val is None:
                    raw_val = stats.get("pnl")
                try:
                    raw_val = float(raw_val)
                except Exception:
                    raw_val = 0.0
                # Bounded reward/penalty using tanh to avoid extreme shifts
                adjustment = math.tanh(raw_val) * reward_scale
                scale = 1.0 + adjustment
                scale = max(min_scale, min(scale, max_scale))
                weighted[name] = weight * scale
            total_weight = sum(weighted.values()) or 0.0
            if total_weight > 0:
                alloc = {k: v / total_weight for k, v in weighted.items()}
        # Normalize and keep only top 3-5 allocations
        alloc = {k: v for k, v in sorted(alloc.items(), key=lambda x: -x[1])[:5]}
        total = sum(alloc.values()) or 1.0
        alloc = {k: v / total for k, v in alloc.items()}
        self.last_guarded_strategies = guarded
        self.last_allocations = alloc
        return alloc

    def route(self, market_state: Dict[str, Any]) -> List[Dict[str, Any]]:
        # Get performance stats
        perf_stats = self.perf_tracker.get_all_stats() if self.perf_tracker else {}
        # Detect regime
        regime = self.detect_regime(market_state)
        self.last_regime = regime
        # Compute allocations
        alloc = self.compute_allocations(regime, perf_stats)
        # Get signals from each strategy
        signals = []
        for s in self.strategies:
            if alloc.get(s.name, 0) > 0:
                try:
                    analyze_fn = getattr(s, "analyze", None)
                    if analyze_fn is None:
                        raise AttributeError("analyze not found")
                    try:
                        sig = analyze_fn(market_state)
                    except Exception:
                        params = signature(analyze_fn).parameters
                        call_args = {}
                        for pname in params:
                            if pname in market_state:
                                call_args[pname] = market_state[pname]
                            elif pname in ("market_state", "state"):
                                call_args[pname] = market_state
                        if not call_args:
                            sig = analyze_fn()
                        else:
                            sig = analyze_fn(**call_args)
                    signals.append(
                        {
                            "strategy": s.name,
                            "allocation": alloc[s.name],
                            "signal": sig,
                        }
                    )
                except Exception as e:
                    signals.append(
                        {
                            "strategy": s.name,
                            "allocation": alloc[s.name],
                            "signal": None,
                            "error": str(e),
                        }
                    )
        return signals

    def get_last_allocations(self):
        return self.last_allocations

    def get_last_regime(self):
        return self.last_regime
