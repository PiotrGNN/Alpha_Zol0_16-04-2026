from core.DynamicStrategyRouter import DynamicStrategyRouter


class _DummyStrategy:
    def __init__(self, name: str):
        self.name = name

    def analyze(self, market_state):
        return {"signal": "hold"}


class _EmptySignalsStrategy:
    name = "MeanReversion"

    def analyze(self, market_state):
        return {"signals": [], "metrics": {}, "analysis": {}}


class _TrendStrengthStrategy:
    name = "TrendFollowing"

    def analyze(self, market_state):
        return {
            "signals": [],
            "metrics": {
                "trend_strength": {
                    "direction": 1,
                    "momentum": 1,
                    "strength": "strong",
                    "score": 3,
                }
            },
            "analysis": {"trend": {"direction": 1}},
        }


def test_detect_regime_accepts_string_trend_labels():
    router = DynamicStrategyRouter(strategies=[_DummyStrategy("Universal")])

    assert router.detect_regime({"trend": "UP", "volatility": 0.6}) == "trend"
    assert router.detect_regime({"trend": "DOWN", "volatility": 0.6}) == "trend"
    assert router.detect_regime({"trend": "SIDE", "volatility": 0.1}) == "sideways"


def test_route_maps_empty_source_signals_to_hold_side():
    router = DynamicStrategyRouter(strategies=[_EmptySignalsStrategy()])

    signals = router.route({"trend": "SIDE", "volatility": 0.01})

    assert signals == [
        {
            "strategy": "MeanReversion",
            "allocation": 0.25,
            "signal": {"signals": [], "metrics": {}, "analysis": {}},
            "raw_side": "signals:empty",
            "raw_side_source": "signal.signals",
            "side": "hold",
        }
    ]


def test_route_prefers_trend_direction_over_empty_signal_list():
    router = DynamicStrategyRouter(strategies=[_TrendStrengthStrategy()])

    signals = router.route({"trend": "SIDE", "volatility": 0.01})

    assert len(signals) == 1
    signal = signals[0]

    assert signal["strategy"] == "TrendFollowing"
    assert signal["allocation"] == 0.25
    assert signal["side"] == "buy"
    assert signal["raw_side_source"] == "signal.analysis.trend"
    assert signal["signal"]["signals"] == []
    assert signal["signal"]["metrics"]["trend_strength"]["direction"] == 1
