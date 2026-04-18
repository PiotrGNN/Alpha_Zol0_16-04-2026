# SystemResilienceMonitor.py – monitoring uptime i niezawodności komponentów
import logging


class SystemResilienceMonitor:
    def __init__(self):
        self.components = {}

    def update(self, name: str, uptime: float, errors: int):
        score = max(0, uptime - errors * 0.1)
        self.components[name] = {"uptime": uptime, "errors": errors, "score": score}
        logging.info(
            f"ResilienceMonitor: {name} uptime={uptime}, errors={errors}, score={score}"
        )

    def resilience_index(self):
        if not self.components:
            return 0
        total_score = sum(c["score"] for c in self.components.values())
        index = total_score / len(self.components)
        logging.info(f"ResilienceMonitor: resilience_index={index}")
        return index
