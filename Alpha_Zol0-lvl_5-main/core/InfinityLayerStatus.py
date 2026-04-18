# InfinityLayerStatus.py – monitorowanie statusu i zdrowia warstwy ∞

import logging
from typing import Dict

logger = logging.getLogger(__name__)


class InfinityLayerStatus:
    def __init__(self):
        self.status: Dict[str, str] = {}
        self.health: Dict[str, float] = {}

    def update_status(self, name: str, status: str):
        self.status[name] = status
        logging.info(f"InfinityLayerStatus: {name} status updated to {status}")

    def update_health(self, name: str, health: float):
        self.health[name] = health
        logging.info(f"InfinityLayerStatus: {name} health updated to {health}")

    def get_status(self, name: str):
        return self.status.get(name, "unknown")

    def get_health(self, name: str):
        return self.health.get(name, 0.0)

    def summary(self):
        return {
            k: {"status": self.status[k], "health": self.health.get(k, 0.0)}
            for k in self.status
        }
