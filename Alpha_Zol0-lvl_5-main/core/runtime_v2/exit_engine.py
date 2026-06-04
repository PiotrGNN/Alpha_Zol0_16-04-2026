from __future__ import annotations

from core.runtime_v2.contracts import CloseDecision, PositionState, QuoteTick
from core.runtime_v2.execution_engine import PaperExecutionEngineV2


class ExitEngineV2:
    def evaluate(
        self,
        *,
        execution_engine: PaperExecutionEngineV2,
        position: PositionState,
        quote: QuoteTick,
        now_ts: float,
    ) -> CloseDecision:
        snapshot = execution_engine.unrealized_snapshot(position, quote)
        age_sec = max(0.0, float(now_ts) - float(position.opened_ts))
        net_pnl = float(snapshot["net_pnl"])
        gross_pnl = float(snapshot["gross_pnl"])
        close_price = float(snapshot["close_price"])

        if net_pnl >= float(position.take_profit_net_usdt):
            return CloseDecision(
                should_close=True,
                reason_code="take_profit_net",
                close_price=close_price,
                unrealized_gross_pnl=gross_pnl,
                unrealized_net_pnl=net_pnl,
                age_sec=age_sec,
            )
        if net_pnl <= (-1.0 * float(position.stop_loss_net_usdt)):
            return CloseDecision(
                should_close=True,
                reason_code="protective_exit",
                close_price=close_price,
                unrealized_gross_pnl=gross_pnl,
                unrealized_net_pnl=net_pnl,
                age_sec=age_sec,
            )
        if age_sec >= float(position.max_hold_sec):
            return CloseDecision(
                should_close=True,
                reason_code="time_decay_exit",
                close_price=close_price,
                unrealized_gross_pnl=gross_pnl,
                unrealized_net_pnl=net_pnl,
                age_sec=age_sec,
            )
        return CloseDecision(
            should_close=False,
            reason_code="hold",
            close_price=close_price,
            unrealized_gross_pnl=gross_pnl,
            unrealized_net_pnl=net_pnl,
            age_sec=age_sec,
        )
