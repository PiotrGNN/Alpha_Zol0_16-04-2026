from ai.SelfPlayArena import SelfPlayArena


def dummy_strategy_1(tick):
    return {
        "pnl": tick.get("price", 0) * 0.1,
        "drawdown": -abs(tick.get("price", 0) * 0.05),
    }


def dummy_strategy_2(tick):
    return {
        "pnl": tick.get("price", 0) * 0.2,
        "drawdown": -abs(tick.get("price", 0) * 0.1),
    }


def test_self_play_arena():
    market_data = [{"price": 100}, {"price": 110}, {"price": 90}]
    arena = SelfPlayArena([dummy_strategy_1, dummy_strategy_2])
    best = arena.run(market_data)
    assert best["strategy"] in ["dummy_strategy_1", "dummy_strategy_2"]
    assert isinstance(best["pnl"], float)
    assert isinstance(best["drawdown"], float)
