from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional


Side = Literal["buy", "sell"]
DecisionText = Literal["buy", "sell", "hold"]


@dataclass(frozen=True)
class QuoteTick:
    symbol: str
    ts_ms: int
    bid: float
    ask: float
    mid: float
    spread_abs: float
    spread_bps: float
    best_bid_size: Optional[float]
    best_ask_size: Optional[float]
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FeatureFrame:
    symbol: str
    ts_ms: int
    mid: float
    ret_1: float
    ret_3: float
    volatility: float
    spread_bps: float
    has_profile: bool
    sample_count: int
    profile_source: str = "rolling_quote_window"
    profile_age_sec: float = 0.0
    profile_span_sec: float = 0.0


@dataclass(frozen=True)
class StrategySignal:
    strategy: str
    direction: DecisionText
    score: float
    confidence: float
    expected_move: float
    reason_code: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EntryCandidate:
    symbol: str
    side: Side
    strategy: str
    score: float
    confidence: float
    expected_move: float
    expected_edge_after_fee: float
    expected_net_after_cost: float
    probability_of_profit: float
    quote: QuoteTick
    feature: FeatureFrame
    reason_code: str
    cost_breakdown: Dict[str, Any] = field(default_factory=dict)
    signal_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderPlan:
    accepted: bool
    reason_code: str
    symbol: str
    side: Side
    strategy: str
    leverage: float
    requested_notional_usdt: float
    capped_notional_usdt: float
    final_notional_usdt: float
    quantity_base: float
    quantity_contracts: float
    contract_multiplier: float
    lot_size: float
    min_contracts: float
    max_contracts: Optional[float]
    entry_price: float
    fee_rate: float
    expected_net_after_full_cost: float
    risk_cap_usdt: float
    expected_move: float
    probability_of_profit: float
    confidence: float
    candidate_reason_code: str
    cost_breakdown: Dict[str, Any] = field(default_factory=dict)
    sizing_trace: Dict[str, Any] = field(default_factory=dict)
    signal_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PositionState:
    position_id: str
    symbol: str
    side: Side
    strategy: str
    opened_ts: float
    open_price: float
    quantity_base: float
    quantity_contracts: float
    leverage: float
    notional_usdt: float
    fee_rate: float
    entry_fee_usdt: float
    take_profit_net_usdt: float
    stop_loss_net_usdt: float
    max_hold_sec: float
    meta: Dict[str, Any] = field(default_factory=dict)
    mfe_unrealized_net: Optional[float] = None
    mae_unrealized_net: Optional[float] = None
    mfe_unrealized_gross: Optional[float] = None
    mae_unrealized_gross: Optional[float] = None
    mfe_age_sec: Optional[float] = None
    mae_age_sec: Optional[float] = None
    mfe_mae_sample_count: int = 0


@dataclass(frozen=True)
class CloseDecision:
    should_close: bool
    reason_code: str
    close_price: float
    unrealized_gross_pnl: float
    unrealized_net_pnl: float
    age_sec: float
