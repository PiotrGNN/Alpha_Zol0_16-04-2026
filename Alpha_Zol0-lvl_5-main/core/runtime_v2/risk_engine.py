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


def _safe_float(value, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


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
        if (
            self.entry_min_net_usdt > 0.0
            and expected_net_after_full_cost < self.entry_min_net_usdt
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
                sizing_trace_extra={
                    "expected_net_after_full_cost": expected_net_after_full_cost,
                    "entry_min_net_usdt": self.entry_min_net_usdt,
                    "estimated_take_profit_net_usdt": estimated_take_profit_net_usdt,
                    "estimated_stop_loss_net_usdt": estimated_stop_loss_net_usdt,
                },
            )
        entry_net_to_stop_ratio = (
            expected_net_after_full_cost / estimated_stop_loss_net_usdt
            if estimated_stop_loss_net_usdt > 0.0
            else float("inf")
        )
        if (
            self.entry_min_net_to_stop_ratio > 0.0
            and entry_net_to_stop_ratio < self.entry_min_net_to_stop_ratio
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
                sizing_trace_extra={
                    "expected_net_after_full_cost": expected_net_after_full_cost,
                    "entry_net_to_stop_ratio": entry_net_to_stop_ratio,
                    "entry_min_net_to_stop_ratio": self.entry_min_net_to_stop_ratio,
                    "estimated_take_profit_net_usdt": estimated_take_profit_net_usdt,
                    "estimated_stop_loss_net_usdt": estimated_stop_loss_net_usdt,
                },
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
