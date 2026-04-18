# QuantumResilienceMonitor.py – monitorowanie odporności i adaptacji systemu
import logging
from typing import Dict


class QuantumResilienceMonitor:
    def __init__(self):
        self.metrics: Dict[str, float] = {}
        self.events: Dict[str, str] = {}

    def update_metric(self, name: str, value: float):
        self.metrics[name] = value
        logging.info(f"QuantumResilienceMonitor: {name} metric updated to {value}")

    def log_event(self, name: str, event: str):
        self.events[name] = event
        logging.info(f"QuantumResilienceMonitor: {name} event logged: {event}")

    def get_metric(self, name: str):
        return self.metrics.get(name, 0.0)

    def get_event(self, name: str):
        return self.events.get(name, "none")

    def summary(self):
        return {
            k: {"metric": self.metrics[k], "event": self.events.get(k, "none")}
            for k in self.metrics
        }
