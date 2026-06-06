from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.runtime_v2.contracts import QuoteTick


@dataclass
class ShadowBlockedCandidate:
    shadow_id: str
    symbol: str
    side: str
    strategy: str
    opened_ts: float
    entry_price: float
    quantity_base: float
    fee_rate: float
    take_profit_net_usdt: float
    stop_loss_net_usdt: float
    max_hold_sec: float
    guard_fields: Dict[str, Any] = field(default_factory=dict)
    mfe_unrealized_net: Optional[float] = None
    mae_unrealized_net: Optional[float] = None
    mfe_age_sec: Optional[float] = None
    mae_age_sec: Optional[float] = None
    last_observed_price: Optional[float] = None
    last_observed_ts: Optional[float] = None
    last_proxy_net: Optional[float] = None
    sample_count: int = 0


class ImmediateAdverseShadowTracker:
    def __init__(self) -> None:
        self._items: Dict[str, ShadowBlockedCandidate] = {}
        self._seq = 0

    @property
    def active_count(self) -> int:
        return len(self._items)

    def add_blocked_candidate(
        self,
        *,
        symbol: str,
        side: str,
        strategy: str,
        opened_ts: float,
        entry_price: float,
        quantity_base: float,
        fee_rate: float,
        take_profit_net_usdt: float,
        stop_loss_net_usdt: float,
        max_hold_sec: float,
        guard_fields: Dict[str, Any],
    ) -> str:
        self._seq += 1
        shadow_id = f"iad-shadow-{self._seq}"
        self._items[shadow_id] = ShadowBlockedCandidate(
            shadow_id=shadow_id,
            symbol=str(symbol).upper(),
            side=str(side).lower(),
            strategy=str(strategy),
            opened_ts=float(opened_ts),
            entry_price=float(entry_price),
            quantity_base=float(quantity_base),
            fee_rate=float(fee_rate),
            take_profit_net_usdt=float(take_profit_net_usdt),
            stop_loss_net_usdt=float(stop_loss_net_usdt),
            max_hold_sec=float(max_hold_sec),
            guard_fields=dict(guard_fields or {}),
        )
        return shadow_id

    def observe_quotes(
        self, quote_by_symbol: Dict[str, QuoteTick], *, now_ts: float
    ) -> List[Dict[str, Any]]:
        terminal: List[Dict[str, Any]] = []
        for shadow_id, item in list(self._items.items()):
            quote = quote_by_symbol.get(item.symbol)
            if quote is None:
                continue
            payload = self._observe_one(item, quote, now_ts=float(now_ts))
            if payload is not None:
                terminal.append(payload)
                self._items.pop(shadow_id, None)
        return terminal

    def flush_expired(
        self,
        quote_by_symbol: Dict[str, QuoteTick],
        *,
        now_ts: float,
        shutdown: bool = False,
    ) -> List[Dict[str, Any]]:
        terminal: List[Dict[str, Any]] = []
        for shadow_id, item in list(self._items.items()):
            quote = quote_by_symbol.get(item.symbol)
            observed_payload = None
            if quote is not None:
                observed_payload = self._observe_one(item, quote, now_ts=float(now_ts))
            if observed_payload is not None:
                terminal.append(observed_payload)
                self._items.pop(shadow_id, None)
                continue

            age_sec = max(0.0, float(now_ts) - item.opened_ts)
            if item.sample_count <= 0:
                if shutdown or age_sec >= item.max_hold_sec:
                    terminal.append(
                        self._terminal_payload(
                            item,
                            now_ts=float(now_ts),
                            reason="shadow_insufficient_quotes",
                            classification="SHADOW_INSUFFICIENT_QUOTES",
                            reason_detail="no_quote_samples",
                        )
                    )
                    self._items.pop(shadow_id, None)
                continue
            if shutdown:
                terminal.append(
                    self._terminal_payload(
                        item,
                        now_ts=float(now_ts),
                        reason="shadow_open_at_shutdown",
                        classification="SHADOW_OPEN_AT_SHUTDOWN",
                        reason_detail="shutdown_unresolved",
                    )
                )
                self._items.pop(shadow_id, None)
            elif age_sec >= item.max_hold_sec:
                classification = (
                    "NEUTRAL_OR_NO_EDGE"
                    if abs(float(item.last_proxy_net or 0.0)) < 1e-12
                    else "SHADOW_EXPIRED_NO_TERMINAL_MOVE"
                )
                terminal.append(
                    self._terminal_payload(
                        item,
                        now_ts=float(now_ts),
                        reason=(
                            "shadow_neutral_or_no_edge"
                            if classification == "NEUTRAL_OR_NO_EDGE"
                            else "shadow_expired_no_terminal_move"
                        ),
                        classification=classification,
                        reason_detail="max_hold_elapsed_without_terminal_move",
                    )
                )
                self._items.pop(shadow_id, None)
        return terminal

    def _observe_one(
        self, item: ShadowBlockedCandidate, quote: QuoteTick, *, now_ts: float
    ) -> Optional[Dict[str, Any]]:
        age_sec = max(0.0, float(now_ts) - item.opened_ts)
        close_price = float(quote.mid)
        if item.side == "buy":
            gross = (close_price - item.entry_price) * item.quantity_base
        else:
            gross = (item.entry_price - close_price) * item.quantity_base
        exit_fee = abs(item.quantity_base * close_price) * item.fee_rate
        entry_fee = abs(item.quantity_base * item.entry_price) * item.fee_rate
        net = gross - entry_fee - exit_fee
        item.sample_count += 1
        item.last_observed_price = close_price
        item.last_observed_ts = float(now_ts)
        item.last_proxy_net = net
        if item.mfe_unrealized_net is None or net > item.mfe_unrealized_net:
            item.mfe_unrealized_net = net
            item.mfe_age_sec = age_sec
        if item.mae_unrealized_net is None or net < item.mae_unrealized_net:
            item.mae_unrealized_net = net
            item.mae_age_sec = age_sec
        reason = None
        if net >= item.take_profit_net_usdt:
            reason = "take_profit_net"
        elif net <= (-1.0 * item.stop_loss_net_usdt):
            reason = "protective_exit"
        elif age_sec >= item.max_hold_sec:
            reason = "time_decay_exit"
        if reason is None:
            return None
        if net > 0:
            classification = "MISSED_WINNER"
        elif (item.mfe_unrealized_net or 0.0) > 0:
            classification = "NEUTRAL_OR_NO_EDGE"
        else:
            classification = "IMMEDIATE_ADVERSE_LOSS"
        return self._terminal_payload(
            item,
            now_ts=float(now_ts),
            reason=reason,
            classification=classification,
            reason_detail=reason,
        )

    def _terminal_payload(
        self,
        item: ShadowBlockedCandidate,
        *,
        now_ts: float,
        reason: str,
        classification: str,
        reason_detail: str,
    ) -> Dict[str, Any]:
        age_sec = max(0.0, float(now_ts) - item.opened_ts)
        last_price = item.last_observed_price
        proxy_net = item.last_proxy_net
        coverage = (
            min(1.0, age_sec / item.max_hold_sec)
            if item.max_hold_sec > 0.0
            else 1.0
        )
        return {
            **dict(item.guard_fields),
            "candidate_id": item.shadow_id,
            "shadow_id": item.shadow_id,
            "symbol": item.symbol,
            "side": item.side,
            "strategy": item.strategy,
            "opened_ts": item.opened_ts,
            "entry_ts": item.opened_ts,
            "close_ts": float(now_ts),
            "final_shadow_ts": float(now_ts),
            "age_sec": age_sec,
            "shadow_duration_sec": age_sec,
            "entry_price": item.entry_price,
            "close_price": last_price,
            "last_observed_price": last_price,
            "quantity_base": item.quantity_base,
            "shadow_exit_reason": reason,
            "shadow_outcome_classification": classification,
            "terminal_classification": classification,
            "realized_proxy_net": proxy_net,
            "proxy_net_result": proxy_net,
            "mfe_unrealized_net": item.mfe_unrealized_net,
            "mae_unrealized_net": item.mae_unrealized_net,
            "max_favorable_net_proxy": item.mfe_unrealized_net,
            "max_adverse_net_proxy": item.mae_unrealized_net,
            "mfe_age_sec": item.mfe_age_sec,
            "mae_age_sec": item.mae_age_sec,
            "shadow_sample_count": item.sample_count,
            "quote_sample_count": item.sample_count,
            "trajectory_coverage": coverage,
            "reason_detail": reason_detail,
        }
