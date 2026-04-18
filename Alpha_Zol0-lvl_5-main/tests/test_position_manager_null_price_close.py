"""
P1-3  close_position() with price=None — null-price silent PnL fallback at shutdown
"""
from core.PositionManager import PositionManager


def test_close_position_with_null_price_does_not_raise():
    """
    When the last-known market price is None (can happen at shutdown before
    first tick), close_position() must not raise and must still move the
    position to closed.  realized_pnl may be None — that is acceptable.
    """
    pm = PositionManager()
    pm.open_position(
        {
            "symbol": "BTCUSDTM",
            "side": "buy",
            "amount": 0.001,
            "entry_price": 90000.0,
            "trade_id": "null-price-001",
            "strategy": "TrendFollowing",
            "timestamp": "2026-04-16T00:00:00+00:00",
        }
    )
    assert pm.get_position("BTCUSDTM") is not None

    # price=None — must not raise TypeError or any other exception
    pm.close_position("BTCUSDTM", price=None, timestamp=1_700_000_000)

    assert pm.get_position("BTCUSDTM") is None, (
        "Position must be removed from active map after close_position(price=None)"
    )
    assert len(pm.closed) == 1, "Position must appear in closed list"
    closed = pm.closed[0]
    # realized_pnl may be None when price is unavailable — that is acceptable
    # but it must not be a non-None, non-numeric garbage value
    rpnl = closed.get("realized_pnl")
    assert rpnl is None or isinstance(rpnl, (int, float)), (
        f"realized_pnl must be None or numeric, got {rpnl!r}"
    )


def test_close_position_with_null_price_short_does_not_raise():
    """Same as above for a short position."""
    pm = PositionManager()
    pm.open_position(
        {
            "symbol": "ETHUSDTM",
            "side": "sell",
            "amount": 0.01,
            "entry_price": 3000.0,
            "trade_id": "null-price-short-001",
            "strategy": "MeanReversion",
            "timestamp": "2026-04-16T00:00:00+00:00",
        }
    )
    pm.close_position("ETHUSDTM", price=None, timestamp=1_700_000_001)

    assert pm.get_position("ETHUSDTM") is None
    assert len(pm.closed) == 1
