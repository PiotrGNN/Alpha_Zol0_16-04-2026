from __future__ import annotations

import os

from core.runtime_v2.contracts import CloseDecision, PositionState, QuoteTick
from core.runtime_v2.execution_engine import PaperExecutionEngineV2


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _paper_post_green_lock_enabled() -> bool:
    if str(os.environ.get("LIVE", "0")).strip() == "1":
        return False
    return str(os.environ.get("V2_PAPER_POST_GREEN_LOCK_ENABLE", "0")).strip() == "1"


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
        execution_engine.observe_unrealized_path(
            position,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            age_sec=age_sec,
        )

        if net_pnl >= float(position.take_profit_net_usdt):
            return CloseDecision(
                should_close=True,
                reason_code="take_profit_net",
                close_price=close_price,
                unrealized_gross_pnl=gross_pnl,
                unrealized_net_pnl=net_pnl,
                age_sec=age_sec,
            )
        if _paper_post_green_lock_enabled():
            mfe_net = position.mfe_unrealized_net
            min_mfe = max(
                0.0,
                _env_float("V2_PAPER_POST_GREEN_LOCK_MIN_MFE_USDT", 0.02),
            )
            retain_ratio = max(
                0.0,
                _env_float("V2_PAPER_POST_GREEN_LOCK_RETAIN_RATIO", 0.25),
            )
            floor_usdt = max(
                0.0,
                _env_float("V2_PAPER_POST_GREEN_LOCK_FLOOR_USDT", 0.005),
            )
            if mfe_net is not None and float(mfe_net) >= min_mfe and net_pnl > 0.0:
                lock_floor = max(floor_usdt, float(mfe_net) * retain_ratio)
                if net_pnl <= lock_floor:
                    return CloseDecision(
                        should_close=True,
                        reason_code="post_green_lock_exit",
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
