# TrendAgent – ocenia trend rynku
class TrendAgent:
    def vote(self, market_data):
        # Przykład: market_data = {'trend': 'UP', 'strength': 0.7}
        if market_data.get("trend") == "UP" and market_data.get("strength", 0) > 0.5:
            return "buy"
        elif (
            market_data.get("trend") == "DOWN" and market_data.get("strength", 0) > 0.5
        ):
            return "sell"
        return "wait"

    def some_method(self):
        # Removed unused variable 'long_line' to avoid assignment
        # without usage.
        pass
