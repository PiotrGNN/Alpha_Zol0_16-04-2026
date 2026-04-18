# KarmaEngine.py – nagradzanie długoterminowo skutecznych modeli
import logging


class KarmaEngine:
    def __init__(self):
        self.model_scores = {}

    def update_score(self, model_id, success):
        if model_id not in self.model_scores:
            self.model_scores[model_id] = 0.0
        self.model_scores[model_id] += 1.0 if success else -0.5
        logging.info(
            f"KarmaEngine: model {model_id} " f"score={self.model_scores[model_id]}"
        )

    def get_weight(self, model_id):
        # Waga rośnie wraz ze skutecznością
        score = self.model_scores.get(model_id, 0.0)
        weight = max(0.1, min(2.0, 1.0 + score / 10.0))
        logging.info(f"KarmaEngine: model {model_id} weight={weight}")
        return weight
