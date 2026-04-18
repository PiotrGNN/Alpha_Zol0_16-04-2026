# AutoHeal.py – automatyczne wykrywanie i naprawa awarii AI
import logging


class AutoHeal:
    def __init__(self):
        self.rollback_count = 0

    def detect_failure(self, model_status, strategy_status):
        # Prosta heurystyka: status == 'error' lub 'regression'
        return model_status in ["error", "regression"] or strategy_status in [
            "error",
            "regression",
        ]

    def heal(self, model, strategy):
        if self.detect_failure(model.status, strategy.status):
            model.rollback()
            strategy.restart()
            self.rollback_count += 1
            logging.info(
                "AutoHeal: rollback model, restart strategy, "
                f"count={self.rollback_count}"
            )
            return True

        return False
