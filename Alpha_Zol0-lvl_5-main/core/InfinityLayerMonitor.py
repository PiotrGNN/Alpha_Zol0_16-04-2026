# InfinityLayerMonitor.py – monitorowanie i automatyczna reakcja na anomalie
# w warstwie ∞
import logging
from typing import Any, Dict

logger = logging.getLogger("InfinityLayerMonitor")


class InfinityLayerMonitor:
    def __init__(self):
        self.anomalies: Dict[str, Any] = {}
        self.actions: Dict[str, str] = {}

    def detect_anomaly(self, name: str, details: Any):
        self.anomalies[name] = details
        logger.warning(f"InfinityLayerMonitor: anomaly detected in {name}: {details}")

    def react(self, name: str, action: str):
        self.actions[name] = action
        logger.info(f"InfinityLayerMonitor: action taken for {name}: {action}")

    def get_anomaly(self, name: str):
        return self.anomalies.get(name, None)

    def get_action(self, name: str):
        return self.actions.get(name, None)

    def summary(self):
        return {
            k: {
                "anomaly": self.anomalies[k],
                "action": self.actions.get(k, None),
            }
            for k in self.anomalies
        }
