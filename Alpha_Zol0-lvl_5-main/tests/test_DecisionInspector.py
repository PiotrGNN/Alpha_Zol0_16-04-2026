from core.DecisionInspector import DecisionInspector


def test_decision_inspector():
    inspector = DecisionInspector()
    features = {
        "trend": "UP",
        "volatility": 20,
        "drawdown": 0.05,
        "tp_score": 0.8,
        "signal_strength": 0.7,
    }
    result = inspector.inspect("buy", features)
    assert result["decision"] == "buy"
    assert result["score"] > 0
    assert 0 <= result["prob_success"] <= 1
    assert "Trend UP" in result["explanation"]
    assert "TP score" in result["explanation"]
