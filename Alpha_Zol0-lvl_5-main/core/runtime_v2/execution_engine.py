from __future__ import annotations

import os
import uuid
from typing import Dict, Optional

from core.runtime_v2.contracts import OrderPlan, PositionState, QuoteTick


class PaperExecutionEngineV2:
    def __init__(self, base_balance_usdt: float):
        self.base_balance_usdt = float(base_balance_usdt)
        self.realized_pnl_usdt = 0.0
        self.positions: Dict[str, PositionState] = {}
        self.fill_mode = str(os.environ.get("V2_FILL_MODE", "mid")).strip().lower()
        if self.fill_mode not in {"mid", "taker"}:
            self.fill_mode = "mid"

    def get_position(self, symbol: str) -> Optional[PositionState]:
        return self.positions.get(str(symbol).upper())

    def open_position(
        self,
        *,
        plan: OrderPlan,
        quote: QuoteTick,
        now_ts: float,
        take_profit_net_usdt: float,
        stop_loss_net_usdt: float,
        max_hold_sec: float,
    ) -> PositionState:
        if self.fill_mode == "taker":
            fill_price = float(quote.ask if plan.side == "buy" else quote.bid)
        else:
            fill_price = float(quote.mid)
        notional = float(plan.quantity_base) * fill_price
        entry_fee_usdt = notional * float(plan.fee_rate)
        position = PositionState(
            position_id=f"v2-{uuid.uuid4().hex[:24]}",
            symbol=plan.symbol,
            side=plan.side,
            strategy=plan.strategy,
            opened_ts=float(now_ts),
            open_price=fill_price,
            quantity_base=float(plan.quantity_base),
            quantity_contracts=float(plan.quantity_contracts),
            leverage=float(plan.leverage),
            notional_usdt=notional,
            fee_rate=float(plan.fee_rate),
            entry_fee_usdt=entry_fee_usdt,
            take_profit_net_usdt=float(take_profit_net_usdt),
            stop_loss_net_usdt=float(stop_loss_net_usdt),
            max_hold_sec=float(max_hold_sec),
            meta={
                "sizing_trace": dict(plan.sizing_trace),
                "cost_breakdown": dict(plan.cost_breakdown),
                "expected_net_after_full_cost": float(plan.expected_net_after_full_cost),
                "expected_move": float(plan.expected_move),
                "probability_of_profit": float(plan.probability_of_profit),
                "confidence": float(plan.confidence),
            },
        )
        self.positions[plan.symbol.upper()] = position
        return position

    def mark_to_market(self, quote_by_symbol: Dict[str, QuoteTick]) -> float:
        total = self.base_balance_usdt + self.realized_pnl_usdt
        for symbol, position in self.positions.items():
            quote = quote_by_symbol.get(symbol)
            if quote is None:
                continue
            total += self._unrealized_net(position, quote)
        return total

    def _unrealized_gross(self, position: PositionState, quote: QuoteTick) -> float:
        if self.fill_mode == "taker":
            close_price = float(quote.bid if position.side == "buy" else quote.ask)
        else:
            close_price = float(quote.mid)
        if position.side == "buy":
            return (close_price - position.open_price) * position.quantity_base
        return (position.open_price - close_price) * position.quantity_base

    def _unrealized_net(self, position: PositionState, quote: QuoteTick) -> float:
        gross = self._unrealized_gross(position, quote)
        if self.fill_mode == "taker":
            close_price = float(quote.bid if position.side == "buy" else quote.ask)
        else:
            close_price = float(quote.mid)
        exit_notional = abs(position.quantity_base * close_price)
        exit_fee = exit_notional * position.fee_rate
        return gross - position.entry_fee_usdt - exit_fee

    def unrealized_snapshot(self, position: PositionState, quote: QuoteTick) -> Dict[str, float]:
        gross = self._unrealized_gross(position, quote)
        if self.fill_mode == "taker":
            close_price = float(quote.bid if position.side == "buy" else quote.ask)
        else:
            close_price = float(quote.mid)
        exit_notional = abs(position.quantity_base * close_price)
        exit_fee = exit_notional * position.fee_rate
        net = gross - position.entry_fee_usdt - exit_fee
        return {
            "close_price": close_price,
            "gross_pnl": gross,
            "exit_fee": exit_fee,
            "net_pnl": net,
        }

    def observe_unrealized_path(
        self,
        position: PositionState,
        *,
        gross_pnl: float,
        net_pnl: float,
        age_sec: float,
    ) -> None:
        gross = float(gross_pnl)
        net = float(net_pnl)
        age = max(0.0, float(age_sec))
        position.mfe_mae_sample_count += 1
        if position.mfe_unrealized_net is None or net > float(position.mfe_unrealized_net):
            position.mfe_unrealized_net = net
            position.mfe_age_sec = age
        if position.mae_unrealized_net is None or net < float(position.mae_unrealized_net):
            position.mae_unrealized_net = net
            position.mae_age_sec = age
        if position.mfe_unrealized_gross is None or gross > float(position.mfe_unrealized_gross):
            position.mfe_unrealized_gross = gross
        if position.mae_unrealized_gross is None or gross < float(position.mae_unrealized_gross):
            position.mae_unrealized_gross = gross

    def close_position(
        self,
        *,
        symbol: str,
        quote: QuoteTick,
        now_ts: float,
        reason_code: str,
    ) -> Optional[Dict]:
        position = self.positions.pop(str(symbol).upper(), None)
        if position is None:
            return None
        if self.fill_mode == "taker":
            close_price = float(quote.bid if position.side == "buy" else quote.ask)
        else:
            close_price = float(quote.mid)
        if position.side == "buy":
            gross = (close_price - position.open_price) * position.quantity_base
        else:
            gross = (position.open_price - close_price) * position.quantity_base
        exit_notional = abs(position.quantity_base * close_price)
        exit_fee = exit_notional * position.fee_rate
        net = gross - position.entry_fee_usdt - exit_fee
        age_sec = max(0.0, float(now_ts) - float(position.opened_ts))
        self.observe_unrealized_path(
            position,
            gross_pnl=gross,
            net_pnl=net,
            age_sec=age_sec,
        )
        self.realized_pnl_usdt += net
        payload = {
            "position_id": position.position_id,
            "symbol": position.symbol,
            "side": position.side,
            "strategy": position.strategy,
            "opened_ts": position.opened_ts,
            "close_timestamp": float(now_ts),
            "open_price": position.open_price,
            "close_price": close_price,
            "quantity_base": position.quantity_base,
            "quantity_contracts": position.quantity_contracts,
            "notional_usdt": position.notional_usdt,
            "exit_notional_usdt": exit_notional,
            "entry_fee_usdt": position.entry_fee_usdt,
            "exit_fee_usdt": exit_fee,
            "realized_gross": gross,
            "realized_pnl": net,
            "mfe_unrealized_net": position.mfe_unrealized_net,
            "mae_unrealized_net": position.mae_unrealized_net,
            "mfe_unrealized_gross": position.mfe_unrealized_gross,
            "mae_unrealized_gross": position.mae_unrealized_gross,
            "mfe_age_sec": position.mfe_age_sec,
            "mae_age_sec": position.mae_age_sec,
            "mfe_mae_sample_count": position.mfe_mae_sample_count,
            "mfe_mae_source": "position_runtime_observed_path",
            "exit_reason": reason_code,
            "close_reason": reason_code,
            "pnl_decompose": {
                "gross_fill_pnl_model": gross,
                "entry_fee": position.entry_fee_usdt,
                "exit_fee": exit_fee,
                "net_pnl": net,
            },
            "meta": dict(position.meta),
        }
        return payload
