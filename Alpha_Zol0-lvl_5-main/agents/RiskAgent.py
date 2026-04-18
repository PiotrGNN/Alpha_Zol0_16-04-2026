# RiskAgent – ocenia ryzyko
class RiskAgent:
    def vote(self, risk_data):
        # Przykład: risk_data = {'drawdown': 0.08, 'volatility': 30}
        if risk_data.get("drawdown", 0) > 0.1:
            return "wait"
        if risk_data.get("volatility", 0) > 50:
            return "wait"
        return "ok"
