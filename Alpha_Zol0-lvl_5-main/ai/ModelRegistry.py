# ModelRegistry.py – rejestr modeli z trust_score
import logging
from datetime import datetime


class ModelRegistry:
    def __init__(self):
        self.models = []

    def register(self, model, trust_score, source, trained_at=None):
        if trained_at is None:
            trained_at = datetime.now().isoformat()
        entry = {
            "model": model,
            "trust_score": trust_score,
            "source": source,
            "trained_at": trained_at,
        }
        self.models.append(entry)
        logging.info("ModelRegistry: registered model with trust_score=%s", trust_score)

    def get_trusted_models(self, min_score=0.6):
        trusted = [m for m in self.models if m["trust_score"] >= min_score]
        logging.info(f"ModelRegistry: trusted models count={len(trusted)}")
        return trusted

    def get_latest(self):
        if not self.models:
            return None
        return sorted(self.models, key=lambda m: m["trained_at"], reverse=True)[0]
