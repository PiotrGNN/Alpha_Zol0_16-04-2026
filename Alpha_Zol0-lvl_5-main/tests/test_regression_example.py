from ai.HypothesisGenerator import HypothesisGenerator


def test_regression_bugfix_123():
    generator = HypothesisGenerator()

    model = generator.get_model()
    hypotheses = generator.generate(
        [
            {
                "symbol": "BTCUSDT",
                "open": 100.0,
                "close": 105.0,
                "volume": 1200,
            }
        ]
    )

    assert hasattr(model, "predict")
    assert len(hypotheses) == 2
    assert hypotheses[0]["expected"] == "UP"
