from models.portfolio_optimizer import QuantumPortfolioOptimizer


def test_quantum_portfolio_optimizer():
    qpo = QuantumPortfolioOptimizer()
    assets = [
        {"symbol": "AAPL", "expected_return": 0.12, "risk": 0.2},
        {"symbol": "MSFT", "expected_return": 0.10, "risk": 0.18},
        {"symbol": "GOOG", "expected_return": 0.15, "risk": 0.25},
    ]
    result = qpo.optimize(assets)
    assert len(result["weights"]) == 3
    assert abs(sum(result["weights"]) - 1) < 1e-6
    assert "expected_return" in result
    assert "risk" in result
    assert result["assets"] == ["AAPL", "MSFT", "GOOG"]
    last = qpo.get_last_result()
    assert last == result


def test_quantum_portfolio_optimizer_empty_assets_returns_none():
    qpo = QuantumPortfolioOptimizer()
    assert qpo.optimize([]) is None
    assert qpo.get_last_result() is None


def test_quantum_portfolio_optimizer_empty_positions_returns_none():
    qpo = QuantumPortfolioOptimizer()
    assert qpo.optimize_portfolio([]) is None
