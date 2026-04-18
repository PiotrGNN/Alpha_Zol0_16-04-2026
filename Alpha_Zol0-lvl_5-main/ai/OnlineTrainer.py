# OnlineTrainer.py – online learning loop dla modelu AI
import json
import logging
import math
import os
import time
import warnings
from pathlib import Path

import numpy as np
from sklearn import __version__ as SKLEARN_VERSION
from sklearn.exceptions import InconsistentVersionWarning
from sklearn.ensemble import GradientBoostingClassifier

MODEL_TYPE = "GradientBoostingClassifier"


class OnlineTrainer:
    def __init__(
        self,
        n_features=5,
        model_path="onlinetrainer_model.pkl",
        max_buffer=1000,
    ):
        self.model = GradientBoostingClassifier()
        self.X = []
        self.y = []
        self.n_features = n_features
        self.trained_steps = 0
        self.model_path = model_path
        self.drift_history = []
        self.max_buffer = max_buffer
        self.reward_history = []
        try:
            self.reward_ema_alpha = float(os.environ.get("AI_REWARD_EMA_ALPHA", "0.2"))
        except Exception:
            self.reward_ema_alpha = 0.2
        try:
            self.hit_ema_alpha = float(os.environ.get("AI_HIT_EMA_ALPHA", "0.2"))
        except Exception:
            self.hit_ema_alpha = 0.2
        try:
            self.reward_scale = float(os.environ.get("AI_REWARD_SCALE", "1.0"))
        except Exception:
            self.reward_scale = 1.0
        try:
            self.weight_min_scale = float(os.environ.get("AI_WEIGHT_MIN_SCALE", "0.25"))
        except Exception:
            self.weight_min_scale = 0.25
        try:
            self.weight_max_scale = float(os.environ.get("AI_WEIGHT_MAX_SCALE", "1.75"))
        except Exception:
            self.weight_max_scale = 1.75
        try:
            self.reward_gain = float(os.environ.get("AI_REWARD_GAIN", "0.6"))
        except Exception:
            self.reward_gain = 0.6
        try:
            self.hit_gain = float(os.environ.get("AI_HIT_GAIN", "0.4"))
        except Exception:
            self.hit_gain = 0.4
        try:
            self.loss_streak_cutoff = int(os.environ.get("AI_LOSS_STREAK_CUTOFF", "3"))
        except Exception:
            self.loss_streak_cutoff = 3
        self.reward_ema = 0.0
        self.hit_ema = 0.5
        self.loss_streak = 0
        self.win_streak = 0
        self._last_diversity_log = 0.0
        self.model_available = False
        self.load_model()

    def _metadata_path(self) -> Path:
        return Path(f"{self.model_path}.meta.json")

    def _model_metadata(self) -> dict:
        return {
            "sklearn_version": SKLEARN_VERSION,
            "model_type": type(self.model).__name__,
        }

    def _write_model_metadata(self) -> None:
        metadata_path = self._metadata_path()
        metadata_path.write_text(
            json.dumps(self._model_metadata(), sort_keys=True),
            encoding="utf-8",
        )

    def _load_model_metadata(self) -> dict | None:
        metadata_path = self._metadata_path()
        if not metadata_path.exists():
            return None
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def _metadata_rejection_reason(self, metadata: dict | None) -> str | None:
        if metadata is None:
            return "metadata_missing_or_invalid"
        if str(metadata.get("sklearn_version") or "") != SKLEARN_VERSION:
            return (
                "sklearn_version_mismatch:"
                f"{metadata.get('sklearn_version')}!={SKLEARN_VERSION}"
            )
        if str(metadata.get("model_type") or "") != MODEL_TYPE:
            return (
                "model_type_mismatch:"
                f"{metadata.get('model_type')}!={MODEL_TYPE}"
            )
        return None

    def _reject_persisted_model(self, reason: str) -> None:
        self.model = GradientBoostingClassifier()
        self.model_available = False
        logging.warning(
            "OnlineTrainer: ignored incompatible sklearn model at %s (%s).",
            self.model_path,
            reason,
        )

    def add_sample(self, features, label):
        if self.model is None:
            self.model = GradientBoostingClassifier()
        self.X.append(features)
        self.y.append(label)
        # Limit buffer size to prevent OOM
        if len(self.X) > self.max_buffer:
            self.X.pop(0)
            self.y.pop(0)
        logging.info(f"OnlineTrainer: sample added, total={len(self.X)}")
        # Optionally, update model immediately for true online learning.
        # This enables real-time adaptation.
        if len(self.X) >= self.n_features:
            self.update_model()

    def fit_if_needed(self, step_interval=10):
        if len(self.X) >= self.n_features and self.trained_steps % step_interval == 0:
            self.update_model()
        self.trained_steps += 1

    def update_model(self):
        import joblib

        X_np = np.array(self.X)
        y_np = np.array(self.y)
        if len(np.unique(y_np)) < 2:
            now = time.time()
            if (now - self._last_diversity_log) >= 300:
                logging.info("OnlineTrainer: not enough class diversity for training.")
                self._last_diversity_log = now
            return
        self.model.fit(X_np, y_np)
        joblib.dump(self.model, self.model_path)
        self._write_model_metadata()
        logging.info(
            "OnlineTrainer: model updated and saved with %d samples",
            len(self.X),
        )

    def load_model(self):
        import joblib

        try:
            if not Path(self.model_path).exists():
                raise FileNotFoundError(self.model_path)
            metadata = self._load_model_metadata()
            rejection_reason = self._metadata_rejection_reason(metadata)
            if rejection_reason is not None:
                self._reject_persisted_model(rejection_reason)
                return
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", InconsistentVersionWarning)
                loaded_model = joblib.load(self.model_path)
            version_warnings = [
                warning
                for warning in caught
                if isinstance(warning.message, InconsistentVersionWarning)
            ]
            if version_warnings:
                self._reject_persisted_model(
                    f"inconsistent_version_warning:{len(version_warnings)}"
                )
                return
            self.model = loaded_model
            logging.info("OnlineTrainer: model loaded from disk.")
            self.model_available = True
        except Exception as e:
            logging.error(f"OnlineTrainer: failed to load model: {e}")
            self.model_available = False

    def error_metrics(self):
        if len(self.X) < self.n_features:
            return None
        X_np = np.array(self.X)
        y_np = np.array(self.y)
        try:
            preds = self.model.predict(X_np)
        except Exception:
            return None
        mse = np.mean((preds - y_np) ** 2)
        acc = np.mean(preds == y_np)
        logging.info(f"OnlineTrainer: MSE={mse:.4f}, Accuracy={acc:.4f}")
        return {"mse": mse, "accuracy": acc}

    def stability_metric(self):
        # Simple stability: variance of predictions
        if len(self.X) < self.n_features:
            return None
        X_np = np.array(self.X)
        try:
            preds = self.model.predict(X_np)
        except Exception:
            return None
        stability = np.var(preds)
        logging.info(f"OnlineTrainer: stability={stability:.4f}")
        return stability

    def drift_metric(self):
        # Concept drift: rolling mean diff of predictions
        if len(self.X) < self.n_features * 2:
            return None
        X_np = np.array(self.X)
        try:
            preds = self.model.predict(X_np)
        except Exception:
            return None
        window = self.n_features
        drift = np.mean(
            np.abs(
                np.diff(
                    [
                        np.mean(preds[max(0, i - window) : i + 1])
                        for i in range(window, len(preds))
                    ]
                )
            )
        )
        self.drift_history.append(drift)
        logging.info(f"OnlineTrainer: drift={drift:.4f}")
        return drift

    def predict(self, features):
        if len(self.X) < self.n_features:
            return None
        try:
            return self.model.predict([features])[0]
        except Exception:
            return None

    def _clamp(self, value, lo, hi):
        return max(lo, min(hi, value))

    def record_trade_outcome(self, reward, predicted_side=None, executed_side=None):
        """
        Reward/penalty feedback loop for the online model.
        - Positive reward increases model influence.
        - Negative reward decreases model influence.
        - If predicted/executed sides align, update hit quality too.
        """
        try:
            reward_val = float(reward)
        except Exception:
            reward_val = 0.0
        self.reward_history.append(reward_val)
        if len(self.reward_history) > self.max_buffer:
            self.reward_history.pop(0)
        scale = self.reward_scale if self.reward_scale > 0 else 1.0
        reward_norm = math.tanh(reward_val / scale)
        alpha = self._clamp(self.reward_ema_alpha, 0.01, 1.0)
        self.reward_ema = (1.0 - alpha) * self.reward_ema + alpha * reward_norm
        avg_reward = sum(self.reward_history) / len(self.reward_history)
        if reward_val > 0:
            self.win_streak += 1
            self.loss_streak = 0
        elif reward_val < 0:
            self.loss_streak += 1
            self.win_streak = 0
        pred = str(predicted_side or "").lower()
        exec_side = str(executed_side or "").lower()
        hit = None
        if pred in ("buy", "sell") and exec_side in ("buy", "sell"):
            # Only score hit quality when the AI vote actually matched
            # the executed side for the trade.
            if pred == exec_side:
                hit = 1.0 if reward_val > 0 else 0.0 if reward_val < 0 else 0.5
        if hit is not None:
            hit_alpha = self._clamp(self.hit_ema_alpha, 0.01, 1.0)
            self.hit_ema = (1.0 - hit_alpha) * self.hit_ema + hit_alpha * hit
        logging.info(
            (
                "OnlineTrainer: reward feedback last=%0.6f avg=%0.6f "
                "ema=%0.4f hit_ema=%0.4f wins=%d losses=%d"
            ),
            reward_val,
            avg_reward,
            self.reward_ema,
            self.hit_ema,
            self.win_streak,
            self.loss_streak,
        )
        return self.get_feedback_stats()

    def record_reward(self, reward):
        # Backwards-compatible alias used in existing call sites.
        return self.record_trade_outcome(reward)

    def get_feedback_stats(self):
        avg_reward = (
            sum(self.reward_history) / len(self.reward_history)
            if self.reward_history
            else 0.0
        )
        return {
            "count": len(self.reward_history),
            "avg_reward": avg_reward,
            "reward_ema": self.reward_ema,
            "hit_ema": self.hit_ema,
            "win_streak": self.win_streak,
            "loss_streak": self.loss_streak,
        }

    def adaptive_vote_weight(self, base_weight):
        """
        Convert static AI weight into adaptive weight based on reward feedback.
        """
        try:
            bw = float(base_weight)
        except Exception:
            return 0.0
        if bw <= 0:
            return 0.0
        score = (
            self.reward_ema * self.reward_gain
            + (self.hit_ema - 0.5) * 2.0 * self.hit_gain
        )
        scale = 1.0 + score
        if self.loss_streak >= max(self.loss_streak_cutoff, 1):
            scale = min(scale, self.weight_min_scale)
        scale = self._clamp(
            scale,
            self.weight_min_scale,
            self.weight_max_scale,
        )
        return bw * scale
