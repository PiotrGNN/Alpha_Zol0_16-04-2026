from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from typing import Dict, Optional

from core.kucoin_futures_client import KucoinFuturesClient
from core.runtime_v2.contracts import EntryCandidate, OrderPlan
from core.runtime_v2.admission_reachability import effective_entry_min_net_usdt


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, str(default)))
    except Exception:
        return float(default)


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except Exception:
        return int(default)


def _env_flag(key: str, default: bool) -> bool:
    raw = str(os.environ.get(key, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _paper_diagnostic_gate_disabled(key: str) -> bool:
    if _env_flag("LIVE", False):
        return False
    if not _env_flag("DIAGNOSTIC_MODE", False):
        return False
    return _env_flag(key, False)


def _paper_immediate_adverse_guard_enabled() -> bool:
    if _env_flag("LIVE", False):
        return False
    return _env_flag("V2_PAPER_IMMEDIATE_ADVERSE_GUARD_ENABLE", False)


_SHADOW_VERIFIED_GUARD_RULE_ID = (
    "SOLUSDTM_buy_TrendFollowingV2_shadow_verified_20260606_000500"
)
_SHADOW_VERIFIED_GUARD_SOURCE_ARTIFACT = (
    "analysis/immediate_adverse_shadow_verified_guard_candidates_long_shadow_current.json"
)
_SHADOW_VERIFIED_GUARD_SYMBOL = "SOLUSDTM"
_SHADOW_VERIFIED_GUARD_SIDE = "buy"
_SHADOW_VERIFIED_GUARD_STRATEGY = "TrendFollowingV2"
_SHADOW_VERIFIED_GUARD_TERMINAL_OUTCOME_COUNT = 18
_SHADOW_VERIFIED_GUARD_IMMEDIATE_ADVERSE_LOSS_COUNT = 7
_SHADOW_VERIFIED_GUARD_MISSED_WINNER_COUNT = 6
_SHADOW_VERIFIED_GUARD_MISSED_WINNER_RATE = 0.3333333333333333
_SHADOW_VERIFIED_GUARD_EXPECTED_NET_BENEFIT = 0.08687323999998789
_SHADOW_VERIFIED_GUARD_AVOIDED_LOSS_PROXY_ABS = 0.22447031999998474
_SHADOW_VERIFIED_GUARD_MISSED_WINNER_PROXY_NET = 0.13759707999999685


def _paper_shadow_verified_adverse_guard_enabled() -> bool:
    if _env_flag("LIVE", False):
        return False
    return _env_flag("V2_PAPER_SHADOW_VERIFIED_ADVERSE_GUARD_ENABLE", False)


def _safe_float(value, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _profile_key(symbol: str, side: str, strategy: str) -> str:
    return f"{str(symbol or '').strip().upper()}:{str(side or '').strip().lower()}:{str(strategy or '').strip()}"


def _profile_blocklist() -> set[str]:
    raw = str(
        os.environ.get(
            "V2_PAPER_IMMEDIATE_ADVERSE_GUARD_PROFILE_BLOCKLIST",
            "SOLUSDTM:buy:TrendFollowingV2",
        )
        or ""
    )
    return {_profile_key(*item.split(":", 2)) for item in raw.split(",") if item.count(":") >= 2}


def _shadow_verified_guard_matches(candidate: EntryCandidate) -> bool:
    return (
        str(candidate.symbol or "").strip().upper() == _SHADOW_VERIFIED_GUARD_SYMBOL
        and str(candidate.side or "").strip().lower() == _SHADOW_VERIFIED_GUARD_SIDE
        and str(candidate.strategy or "").strip() == _SHADOW_VERIFIED_GUARD_STRATEGY
    )


def _shadow_verified_guard_trace(candidate: EntryCandidate) -> Dict[str, object]:
    matched = _shadow_verified_guard_matches(candidate)
    return {
        "shadow_verified_guard_evaluated": True,
        "shadow_verified_guard_allowed": not matched,
        "shadow_verified_guard_blocked": bool(matched),
        "shadow_verified_guard_rule_id": _SHADOW_VERIFIED_GUARD_RULE_ID,
        "shadow_verified_guard_reason": (
            "verified_rule_matched" if matched else "rule_not_matched"
        ),
        "shadow_verified_guard_symbol": str(candidate.symbol or "").strip().upper(),
        "shadow_verified_guard_side": str(candidate.side or "").strip().lower(),
        "shadow_verified_guard_strategy": str(candidate.strategy or "").strip(),
        "shadow_verified_guard_source_artifact": _SHADOW_VERIFIED_GUARD_SOURCE_ARTIFACT,
        "shadow_verified_guard_terminal_outcome_count": (
            _SHADOW_VERIFIED_GUARD_TERMINAL_OUTCOME_COUNT
        ),
        "shadow_verified_guard_immediate_adverse_loss_count": (
            _SHADOW_VERIFIED_GUARD_IMMEDIATE_ADVERSE_LOSS_COUNT
        ),
        "shadow_verified_guard_missed_winner_count": (
            _SHADOW_VERIFIED_GUARD_MISSED_WINNER_COUNT
        ),
        "shadow_verified_guard_missed_winner_rate": (
            _SHADOW_VERIFIED_GUARD_MISSED_WINNER_RATE
        ),
        "shadow_verified_guard_expected_net_benefit": (
            _SHADOW_VERIFIED_GUARD_EXPECTED_NET_BENEFIT
        ),
        "shadow_verified_guard_avoided_loss_proxy_abs": (
            _SHADOW_VERIFIED_GUARD_AVOIDED_LOSS_PROXY_ABS
        ),
        "shadow_verified_guard_missed_winner_proxy_net": (
            _SHADOW_VERIFIED_GUARD_MISSED_WINNER_PROXY_NET
        ),
    }


def _round_down_step(value: float, step: float) -> float:
    if step <= 0:
        return float(value)
    return math.floor(float(value) / float(step)) * float(step)


@dataclass
class ContractSpec:
    symbol: str
    multiplier: float
    lot_size: float
    min_size: float
    max_size: Optional[float]


class ContractSpecResolver:
    def __init__(self):
        self._cache: Dict[str, tuple[float, ContractSpec]] = {}
        self._ttl_sec = max(10, _env_int("V2_CONTRACT_CACHE_TTL_SEC", 300))

    def _fallback_spec(self, symbol: str) -> ContractSpec:
        return ContractSpec(
            symbol=symbol,
            multiplier=1.0,
            lot_size=1.0,
            min_size=1.0,
            max_size=None,
        )

    def get(self, symbol: str) -> ContractSpec:
        symbol_key = str(symbol or "").strip().upper()
        now = time.time()
        cached = self._cache.get(symbol_key)
        if cached is not None and (now - cached[0]) <= self._ttl_sec:
            return cached[1]
        try:
            client = KucoinFuturesClient()
            payload = client.get_contract(symbol_key)
            multiplier = _safe_float(payload.get("multiplier"), 1.0)
            lot_size = _safe_float(
                payload.get("lotSize") or payload.get("lot"), 1.0
            )
            min_size = _safe_float(
                payload.get("minSize") or payload.get("minOrderSize"), lot_size
            )
            max_size_raw = payload.get("maxOrderQty") or payload.get("maxSize")
            max_size = None
            try:
                if max_size_raw is not None:
                    max_size = float(max_size_raw)
            except Exception:
                max_size = None
            spec = ContractSpec(
                symbol=symbol_key,
                multiplier=max(multiplier, 1e-12),
                lot_size=max(lot_size, 1e-12),
                min_size=max(min_size, 1e-12),
                max_size=max_size if (max_size is None or max_size > 0) else None,
            )
        except Exception:
            spec = self._fallback_spec(symbol_key)
        self._cache[symbol_key] = (now, spec)
        return spec


class RiskEngineV2:
    def __init__(self):
        self.leverage = max(1.0, _env_float("FUTURES_LEVERAGE", _env_float("futures_leverage", 3.0)))
        self.base_notional_usdt = max(1.0, _env_float("V2_BASE_NOTIONAL_USDT", 25.0))
        self.min_notional_usdt = max(0.5, _env_float("V2_MIN_NOTIONAL_USDT", 5.0))
        self.max_notional_usdt = max(self.min_notional_usdt, _env_float("V2_MAX_NOTIONAL_USDT", 80.0))
        self.risk_cap_fraction = min(1.0, max(0.001, _env_float("V2_RISK_CAP_FRACTION", 0.03)))
        self.max_open_positions = max(1, _env_int("MAX_OPEN_POSITIONS", 3))
        self.max_contracts_env = _env_float("futures_max_contracts_per_trade", 0.0)
        if self.max_contracts_env <= 0:
            self.max_contracts_env = _env_float("FUTURES_MAX_CONTRACTS_PER_TRADE", 0.0)
        self.default_entry_min_net_usdt = max(
            0.0, _env_float("ENTRY_MIN_NET_USDT", 0.0)
        )
        self.entry_min_net_usdt = max(
            0.0,
            effective_entry_min_net_usdt(self.default_entry_min_net_usdt),
        )
        self.entry_min_net_to_stop_ratio = max(
            0.0, _env_float("ENTRY_MIN_NET_TO_STOP_RATIO", 0.0)
        )
        self.base_take_profit_net_usdt = max(
            0.01, _env_float("V2_TAKE_PROFIT_NET_USDT", 0.03)
        )
        self.base_stop_loss_net_usdt = max(
            0.01, _env_float("V2_STOP_LOSS_NET_USDT", 0.06)
        )
        self.use_expected_exit_targets = _env_flag(
            "V2_EXIT_USE_EXPECTED_NET_TARGETS", True
        )
        self.exit_tp_expected_mult = max(
            0.10, _env_float("V2_EXIT_TP_EXPECTED_MULT", 0.85)
        )
        self.exit_sl_expected_mult = max(
            0.10, _env_float("V2_EXIT_SL_EXPECTED_MULT", 1.10)
        )
        self.exit_tp_min_usdt = max(0.001, _env_float("V2_EXIT_TP_MIN_USDT", 0.005))
        self.exit_sl_min_usdt = max(0.001, _env_float("V2_EXIT_SL_MIN_USDT", 0.007))
        self.spec_resolver = ContractSpecResolver()

    def _estimate_exit_targets(self, expected_net_after_full_cost: float) -> Dict[str, float]:
        take_profit_target = max(0.01, float(self.base_take_profit_net_usdt))
        stop_loss_target = max(0.01, float(self.base_stop_loss_net_usdt))
        expected_net_usdt = max(0.0, float(expected_net_after_full_cost))
        if self.use_expected_exit_targets and expected_net_usdt > 0.0:
            dynamic_tp = max(
                float(self.exit_tp_min_usdt),
                expected_net_usdt * float(self.exit_tp_expected_mult),
            )
            dynamic_sl = max(
                float(self.exit_sl_min_usdt),
                expected_net_usdt * float(self.exit_sl_expected_mult),
            )
            take_profit_target = min(take_profit_target, dynamic_tp)
            stop_loss_target = min(
                stop_loss_target, max(dynamic_sl, take_profit_target * 0.90)
            )
            take_profit_target = max(0.01, take_profit_target)
            stop_loss_target = max(0.01, stop_loss_target)
        return {
            "take_profit_net_usdt": float(take_profit_target),
            "stop_loss_net_usdt": float(stop_loss_target),
        }

    def build_order_plan(
        self,
        *,
        candidate: EntryCandidate,
        free_equity_usdt: float,
        open_positions_count: int,
    ) -> OrderPlan:
        spec = self.spec_resolver.get(candidate.symbol)
        price = max(1e-12, float(candidate.quote.mid))
        confidence = max(0.0, min(1.0, float(candidate.confidence)))
        volatility = max(0.0, float(candidate.feature.volatility))
        vol_scale = 1.0 / (1.0 + (volatility * 800.0))
        confidence_scale = 0.70 + (confidence * 0.90)
        requested_notional_usdt = self.base_notional_usdt * confidence_scale * vol_scale
        risk_cap_usdt = max(0.0, float(free_equity_usdt) * self.risk_cap_fraction * self.leverage)
        capped_notional_usdt = min(
            self.max_notional_usdt,
            max(self.min_notional_usdt, requested_notional_usdt),
            risk_cap_usdt if risk_cap_usdt > 0 else self.max_notional_usdt,
        )
        if open_positions_count >= self.max_open_positions:
            return self._reject_plan(
                candidate=candidate,
                spec=spec,
                price=price,
                reason_code="current_side",
                requested_notional_usdt=requested_notional_usdt,
                capped_notional_usdt=capped_notional_usdt,
                risk_cap_usdt=risk_cap_usdt,
            )
        if capped_notional_usdt < self.min_notional_usdt:
            return self._reject_plan(
                candidate=candidate,
                spec=spec,
                price=price,
                reason_code="risk_cap",
                requested_notional_usdt=requested_notional_usdt,
                capped_notional_usdt=capped_notional_usdt,
                risk_cap_usdt=risk_cap_usdt,
            )

        quantity_base_raw = capped_notional_usdt / price
        contracts_raw = quantity_base_raw / spec.multiplier
        contracts = _round_down_step(contracts_raw, spec.lot_size)
        if spec.max_size is not None:
            contracts = min(contracts, spec.max_size)
        if self.max_contracts_env > 0:
            contracts = min(contracts, self.max_contracts_env)
        if contracts < spec.min_size:
            return self._reject_plan(
                candidate=candidate,
                spec=spec,
                price=price,
                reason_code="min_size",
                requested_notional_usdt=requested_notional_usdt,
                capped_notional_usdt=capped_notional_usdt,
                risk_cap_usdt=risk_cap_usdt,
                quantity_contracts=contracts,
            )
        quantity_base = contracts * spec.multiplier
        final_notional_usdt = quantity_base * price
        expected_net_after_full_cost = candidate.expected_net_after_cost * final_notional_usdt
        if expected_net_after_full_cost <= 0:
            return self._reject_plan(
                candidate=candidate,
                spec=spec,
                price=price,
                reason_code="entry_edge_filtered",
                requested_notional_usdt=requested_notional_usdt,
                capped_notional_usdt=capped_notional_usdt,
                risk_cap_usdt=risk_cap_usdt,
                quantity_contracts=contracts,
                final_notional_usdt=final_notional_usdt,
                expected_net_after_full_cost=expected_net_after_full_cost,
                sizing_trace_extra={
                    "expected_net_after_full_cost": expected_net_after_full_cost,
                },
            )
        exit_targets = self._estimate_exit_targets(expected_net_after_full_cost)
        estimated_stop_loss_net_usdt = float(exit_targets["stop_loss_net_usdt"])
        estimated_take_profit_net_usdt = float(exit_targets["take_profit_net_usdt"])
        immediate_adverse_guard_trace = None
        shadow_verified_guard_trace = None
        if _paper_immediate_adverse_guard_enabled():
            guard_profile = _profile_key(
                candidate.symbol, candidate.side, candidate.strategy
            )
            quarantined_profiles = _profile_blocklist()
            is_quarantined = guard_profile in quarantined_profiles
            historical_immediate_adverse_rate = (
                _env_float("V2_PAPER_IMMEDIATE_ADVERSE_GUARD_HIST_RATE", 0.75)
                if is_quarantined
                else 0.0
            )
            historical_tail_loss_net = (
                _env_float("V2_PAPER_IMMEDIATE_ADVERSE_GUARD_HIST_TAIL_LOSS_NET", -0.647601055)
                if is_quarantined
                else 0.0
            )
            risk_score = historical_immediate_adverse_rate
            guard_threshold = max(
                0.0,
                _env_float("V2_PAPER_IMMEDIATE_ADVERSE_GUARD_THRESHOLD", 0.50),
            )
            would_block_unverified = bool(is_quarantined and risk_score >= guard_threshold)
            immediate_adverse_guard_trace = {
                "immediate_adverse_guard_evaluated": True,
                "immediate_adverse_guard_type": "SYMBOL_SIDE_PROFILE_QUARANTINE",
                "immediate_adverse_guard_reason": (
                    "shadow_net_benefit_unverified"
                    if would_block_unverified
                    else "profile_not_quarantined"
                ),
                "symbol": candidate.symbol,
                "side": candidate.side,
                "strategy": candidate.strategy,
                "expected_net": expected_net_after_full_cost,
                "probability": float(candidate.probability_of_profit),
                "risk_score": risk_score,
                "guard_threshold": guard_threshold,
                "historical_immediate_adverse_rate": historical_immediate_adverse_rate,
                "historical_tail_loss_net": historical_tail_loss_net,
                "shadow_verified_guard_required": bool(would_block_unverified),
                "immediate_adverse_guard_shadow_candidate": bool(would_block_unverified),
                "immediate_adverse_guard_blocked": False,
                "immediate_adverse_guard_allowed": True,
            }
        if _paper_shadow_verified_adverse_guard_enabled():
            shadow_verified_guard_trace = _shadow_verified_guard_trace(candidate)
            if bool(shadow_verified_guard_trace["shadow_verified_guard_blocked"]):
                reject_trace = {
                    "expected_net_after_full_cost": expected_net_after_full_cost,
                    "estimated_take_profit_net_usdt": estimated_take_profit_net_usdt,
                    "estimated_stop_loss_net_usdt": estimated_stop_loss_net_usdt,
                }
                if immediate_adverse_guard_trace:
                    reject_trace.update(immediate_adverse_guard_trace)
                reject_trace.update(shadow_verified_guard_trace)
                return self._reject_plan(
                    candidate=candidate,
                    spec=spec,
                    price=price,
                    reason_code="entry_shadow_verified_immediate_adverse_guard",
                    requested_notional_usdt=requested_notional_usdt,
                    capped_notional_usdt=capped_notional_usdt,
                    risk_cap_usdt=risk_cap_usdt,
                    quantity_contracts=contracts,
                    final_notional_usdt=final_notional_usdt,
                    expected_net_after_full_cost=expected_net_after_full_cost,
                    sizing_trace_extra=reject_trace,
                )
        if (
            self.entry_min_net_usdt > 0.0
            and expected_net_after_full_cost < self.entry_min_net_usdt
        ):
            entry_min_net_trace = {
                "expected_net_after_full_cost": expected_net_after_full_cost,
                "entry_min_net_usdt": self.entry_min_net_usdt,
                "estimated_take_profit_net_usdt": estimated_take_profit_net_usdt,
                "estimated_stop_loss_net_usdt": estimated_stop_loss_net_usdt,
            }
            if immediate_adverse_guard_trace:
                entry_min_net_trace.update(immediate_adverse_guard_trace)
            if shadow_verified_guard_trace:
                entry_min_net_trace.update(shadow_verified_guard_trace)
            if not _paper_diagnostic_gate_disabled(
                "DIAG_DISABLE_ENTRY_MIN_NET_GUARD"
            ):
                return self._reject_plan(
                    candidate=candidate,
                    spec=spec,
                    price=price,
                    reason_code="entry_min_net_guard",
                    requested_notional_usdt=requested_notional_usdt,
                    capped_notional_usdt=capped_notional_usdt,
                    risk_cap_usdt=risk_cap_usdt,
                    quantity_contracts=contracts,
                    final_notional_usdt=final_notional_usdt,
                    expected_net_after_full_cost=expected_net_after_full_cost,
                    sizing_trace_extra=entry_min_net_trace,
                )
            diagnostic_gate_skips = [
                {
                    "gate_skipped": True,
                    "gate_name": "entry_min_net_guard",
                    "skip_reason": "diagnostic_override",
                    "expected_net_after_full_cost": expected_net_after_full_cost,
                    "entry_min_net_usdt": self.entry_min_net_usdt,
                    "effective_threshold_source": "ENTRY_MIN_NET_USDT",
                    "diagnostic_flag": "DIAG_DISABLE_ENTRY_MIN_NET_GUARD",
                }
            ]
        else:
            diagnostic_gate_skips = []
        entry_net_to_stop_ratio = (
            expected_net_after_full_cost / estimated_stop_loss_net_usdt
            if estimated_stop_loss_net_usdt > 0.0
            else float("inf")
        )
        if (
            self.entry_min_net_to_stop_ratio > 0.0
            and entry_net_to_stop_ratio < self.entry_min_net_to_stop_ratio
        ):
            entry_stop_trace = {
                "expected_net_after_full_cost": expected_net_after_full_cost,
                "entry_net_to_stop_ratio": entry_net_to_stop_ratio,
                "entry_min_net_to_stop_ratio": self.entry_min_net_to_stop_ratio,
                "estimated_take_profit_net_usdt": estimated_take_profit_net_usdt,
                "estimated_stop_loss_net_usdt": estimated_stop_loss_net_usdt,
            }
            if immediate_adverse_guard_trace:
                entry_stop_trace.update(immediate_adverse_guard_trace)
            if shadow_verified_guard_trace:
                entry_stop_trace.update(shadow_verified_guard_trace)
            if not _paper_diagnostic_gate_disabled(
                "DIAG_DISABLE_ENTRY_NET_TO_STOP_GUARD"
            ):
                return self._reject_plan(
                    candidate=candidate,
                    spec=spec,
                    price=price,
                    reason_code="entry_net_to_stop_guard",
                    requested_notional_usdt=requested_notional_usdt,
                    capped_notional_usdt=capped_notional_usdt,
                    risk_cap_usdt=risk_cap_usdt,
                    quantity_contracts=contracts,
                    final_notional_usdt=final_notional_usdt,
                    expected_net_after_full_cost=expected_net_after_full_cost,
                    sizing_trace_extra=entry_stop_trace,
                )
            diagnostic_gate_skips.append(
                {
                    "gate_skipped": True,
                    "gate_name": "entry_net_to_stop_guard",
                    "skip_reason": "diagnostic_override",
                    "expected_net_after_full_cost": expected_net_after_full_cost,
                    "entry_net_to_stop_ratio": entry_net_to_stop_ratio,
                    "entry_min_net_to_stop_ratio": self.entry_min_net_to_stop_ratio,
                    "effective_threshold_source": "ENTRY_MIN_NET_TO_STOP_RATIO",
                    "diagnostic_flag": "DIAG_DISABLE_ENTRY_NET_TO_STOP_GUARD",
                }
            )

        sizing_trace = {
            "requested_notional_usdt": requested_notional_usdt,
            "capped_notional_usdt": capped_notional_usdt,
            "final_notional_usdt": final_notional_usdt,
            "risk_cap_usdt": risk_cap_usdt,
            "leverage": self.leverage,
            "quantity_base_raw": quantity_base_raw,
            "quantity_contracts_raw": contracts_raw,
            "quantity_contracts": contracts,
            "contract_multiplier": spec.multiplier,
            "lot_size": spec.lot_size,
            "min_contracts": spec.min_size,
            "max_contracts": spec.max_size,
            "expected_net_after_full_cost": expected_net_after_full_cost,
            "estimated_take_profit_net_usdt": estimated_take_profit_net_usdt,
            "estimated_stop_loss_net_usdt": estimated_stop_loss_net_usdt,
            "entry_net_to_stop_ratio": entry_net_to_stop_ratio,
        }
        if immediate_adverse_guard_trace:
            sizing_trace.update(immediate_adverse_guard_trace)
        if shadow_verified_guard_trace:
            sizing_trace.update(shadow_verified_guard_trace)
        if diagnostic_gate_skips:
            sizing_trace["diagnostic_gate_skips"] = diagnostic_gate_skips
        return OrderPlan(
            accepted=True,
            reason_code="allow",
            symbol=candidate.symbol,
            side=candidate.side,
            strategy=candidate.strategy,
            leverage=self.leverage,
            requested_notional_usdt=requested_notional_usdt,
            capped_notional_usdt=capped_notional_usdt,
            final_notional_usdt=final_notional_usdt,
            quantity_base=quantity_base,
            quantity_contracts=contracts,
            contract_multiplier=spec.multiplier,
            lot_size=spec.lot_size,
            min_contracts=spec.min_size,
            max_contracts=spec.max_size,
            entry_price=price,
            fee_rate=float(candidate.cost_breakdown.get("fee_rate", 0.0)),
            expected_net_after_full_cost=expected_net_after_full_cost,
            risk_cap_usdt=risk_cap_usdt,
            expected_move=float(candidate.expected_move),
            probability_of_profit=float(candidate.probability_of_profit),
            confidence=float(candidate.confidence),
            candidate_reason_code=candidate.reason_code,
            cost_breakdown=dict(candidate.cost_breakdown),
            sizing_trace=sizing_trace,
            signal_metadata=dict(candidate.signal_metadata),
        )

    def _reject_plan(
        self,
        *,
        candidate: EntryCandidate,
        spec: ContractSpec,
        price: float,
        reason_code: str,
        requested_notional_usdt: float,
        capped_notional_usdt: float,
        risk_cap_usdt: float,
        quantity_contracts: float = 0.0,
        final_notional_usdt: float = 0.0,
        expected_net_after_full_cost: float = 0.0,
        sizing_trace_extra: Optional[Dict[str, float]] = None,
    ) -> OrderPlan:
        sizing_trace = {
            "requested_notional_usdt": requested_notional_usdt,
            "capped_notional_usdt": capped_notional_usdt,
            "final_notional_usdt": final_notional_usdt,
            "risk_cap_usdt": risk_cap_usdt,
            "quantity_contracts": quantity_contracts,
        }
        if sizing_trace_extra:
            sizing_trace.update(dict(sizing_trace_extra))
        return OrderPlan(
            accepted=False,
            reason_code=reason_code,
            symbol=candidate.symbol,
            side=candidate.side,
            strategy=candidate.strategy,
            leverage=self.leverage,
            requested_notional_usdt=requested_notional_usdt,
            capped_notional_usdt=capped_notional_usdt,
            final_notional_usdt=final_notional_usdt,
            quantity_base=max(0.0, quantity_contracts * spec.multiplier),
            quantity_contracts=max(0.0, quantity_contracts),
            contract_multiplier=spec.multiplier,
            lot_size=spec.lot_size,
            min_contracts=spec.min_size,
            max_contracts=spec.max_size,
            entry_price=price,
            fee_rate=float(candidate.cost_breakdown.get("fee_rate", 0.0)),
            expected_net_after_full_cost=float(expected_net_after_full_cost),
            risk_cap_usdt=risk_cap_usdt,
            expected_move=float(candidate.expected_move),
            probability_of_profit=float(candidate.probability_of_profit),
            confidence=float(candidate.confidence),
            candidate_reason_code=candidate.reason_code,
            cost_breakdown=dict(candidate.cost_breakdown),
            sizing_trace=sizing_trace,
            signal_metadata=dict(candidate.signal_metadata),
        )
