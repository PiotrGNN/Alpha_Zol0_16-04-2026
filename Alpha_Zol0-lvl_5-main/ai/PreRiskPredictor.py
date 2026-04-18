# PreRiskPredictor.py – predykcja ryzyka przed zleceniem
import logging

import numpy as np
from xgboost import XGBClassifier

logger = logging.getLogger("PreRiskPredictor")


class PreRiskPredictor:
    def __init__(self, n_features=3, model_path="prerisk_model.pkl"):
        self.model = XGBClassifier()
        self.X = []
        self.y = []
        self.n_features = n_features
        self.trained_steps = 0
        self.model_path = model_path
        self.drift_history = []
        self.load_model()

    def add_sample(self, features, label):
        """
        Add a new sample (features, label) to the training set.
        Args:
            features (list or np.ndarray): Feature vector.
            label (int or float): Target label.
        """
        if isinstance(features, np.ndarray):
            features = features.tolist()
        self.X.append(features)
        self.y.append(label)
        logging.debug(f"PreRiskPredictor: Added sample X={features}, y={label}")

    def predict(self, X):
        """
        Predict risk class for given features X.
        Args:
            X (list or np.ndarray): Feature vector(s).
        Returns:
            np.ndarray: Predicted class labels.
        """
        X_np = np.array(X)
        try:
            preds = self.model.predict(X_np)
            logging.debug(f"PreRiskPredictor: Predicted {preds} for X={X}")
            return preds
        except Exception as e:
            logging.error(f"PreRiskPredictor: Prediction failed: {e}")
            return None

    def fit_if_needed(self, step_interval=10):
        if len(self.X) >= self.n_features and self.trained_steps % step_interval == 0:
            self.update_model()
        self.trained_steps += 1

    def update_model(self):
        import joblib

        X_np = np.array(self.X)
        y_np = np.array(self.y)
        if len(np.unique(y_np)) < 2:
            logging.warning(
                "PreRiskPredictor: not enough class diversity for training."
            )
            return
        self.model.fit(X_np, y_np)
        joblib.dump(self.model, self.model_path)
        logging.info(
            f"PreRiskPredictor: model updated and saved with " f"{len(self.X)} samples"
        )

    def load_model(self):
        import joblib

        try:
            self.model = joblib.load(self.model_path)
            logging.info("PreRiskPredictor: model loaded from disk.")
        except Exception as exc:
            logging.warning(
                "PreRiskPredictor: model load skipped path=%s error=%s",
                self.model_path,
                exc,
            )

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
        logging.info(f"PreRiskPredictor: MSE={mse:.4f}, Accuracy={acc:.4f}")
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
        logging.info(f"PreRiskPredictor: stability={stability:.4f}")
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
        logging.info(f"PreRiskPredictor: drift={drift:.4f}")
        return drift
