# OmegaResilienceMonitor.py – monitorowanie odporności i stabilności systemu
import logging
from typing import Dict


class OmegaResilienceMonitor:
    def __init__(self):
        self.metrics: Dict[str, float] = {}
        self.status: Dict[str, str] = {}

    def update_metric(self, name: str, value: float):
        self.metrics[name] = value
        logging.info(f"OmegaResilienceMonitor: metric {name} updated to {value}")

    def update_status(self, name: str, status: str):
        self.status[name] = status
        logging.info(f"OmegaResilienceMonitor: status {name} updated to {status}")

    def get_metric(self, name: str):
        return self.metrics.get(name, 0.0)

    def get_status(self, name: str):
        return self.status.get(name, "unknown")

    def summary(self):
        return {
            k: {
                "metric": self.metrics[k],
                "status": self.status.get(k, "unknown"),
            }
            for k in self.metrics
        }
