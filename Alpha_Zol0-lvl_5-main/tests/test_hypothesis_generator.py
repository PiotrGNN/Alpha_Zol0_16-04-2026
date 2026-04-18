from ai.HypothesisGenerator import HypothesisGenerator


def test_hypothesis_generator_lazy_model_and_generation():
    generator = HypothesisGenerator()

    first_model = generator.get_model()
    second_model = generator.get_model()

    assert first_model is second_model
    assert hasattr(first_model, "predict")

    hypotheses = generator.generate(
        [
            {"symbol": "BTCUSDT", "open": 1.0, "close": 2.0, "volume": 1200},
            {"symbol": "ETHUSDT", "open": 2.0, "close": 1.0, "volume": 500},
        ]
    )

    assert len(hypotheses) == 4
    assert hypotheses[0]["expected"] == "UP"
    assert hypotheses[1]["expected"] == "HIGH"


def test_hypothesis_generator_generate_uses_model_prediction(monkeypatch):
    generator = HypothesisGenerator()

    class FakeModel:
        def predict(self, market_data):
            return [{"symbol": "BTCUSDT", "type": "trend", "expected": "UP"}]

    monkeypatch.setattr(generator, "get_model", lambda: FakeModel())

    hypotheses = generator.generate([{"symbol": "BTCUSDT", "open": 1.0, "close": 2.0}])

    assert hypotheses == [{"symbol": "BTCUSDT", "type": "trend", "expected": "UP"}]
