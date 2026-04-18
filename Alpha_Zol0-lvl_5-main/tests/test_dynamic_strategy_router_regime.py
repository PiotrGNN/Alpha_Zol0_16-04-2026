from core.DynamicStrategyRouter import DynamicStrategyRouter


class _DummyStrategy:
    def __init__(self, name: str):
        self.name = name

    def analyze(self, market_state):
        return {"signal": "hold"}


def test_detect_regime_accepts_string_trend_labels():
    router = DynamicStrategyRouter(strategies=[_DummyStrategy("Universal")])

    assert router.detect_regime({"trend": "UP", "volatility": 0.6}) == "trend"
    assert router.detect_regime({"trend": "DOWN", "volatility": 0.6}) == "trend"
    assert router.detect_regime({"trend": "SIDE", "volatility": 0.1}) == "sideways"
