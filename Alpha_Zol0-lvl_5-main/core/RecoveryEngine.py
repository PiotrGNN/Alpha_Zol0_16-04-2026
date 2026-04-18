# RecoveryEngine.py – automatyczne wykrywanie i naprawa błędów, restartów,
# anomalii
import logging
from typing import Callable, List

logger = logging.getLogger(__name__)


class RecoveryEngine:
    def __init__(self):
        self.recovery_actions: List[Callable] = []

    def register_action(self, action: Callable):
        self.recovery_actions.append(action)
        logger.info(f"RecoveryEngine: registered action {action.__name__}")

    def detect_and_recover(self, error: Exception):
        logging.warning(f"RecoveryEngine: detected error {error}")
        for action in self.recovery_actions:
            try:
                action(error)
                logger.info(f"RecoveryEngine: action {action.__name__} succeeded")
            except Exception as e:
                logger.error(f"RecoveryEngine: action {action.__name__} failed: {e}")
