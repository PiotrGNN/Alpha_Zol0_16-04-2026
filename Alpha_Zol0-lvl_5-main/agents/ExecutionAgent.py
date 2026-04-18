# ExecutionAgent – ocenia warunki egzekucji
class ExecutionAgent:
    def vote(self, exec_data):
        # Przykład: exec_data = {'liquidity': 1000, 'spread': 0.1}
        if exec_data.get("liquidity", 0) < 500:
            return "wait"
        if exec_data.get("spread", 0) > 0.2:
            return "wait"
        return "ok"
