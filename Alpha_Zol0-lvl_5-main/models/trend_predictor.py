"""
trend_predictor.py – Production-grade Trend Classification (LEVEL-ML DONE)
- Advanced feature engineering (multi-timeframe, volatility, volume, etc.)
- Robust ML models: RandomForest/XGBoost (classic), LSTM (deep)
- Model persistence, retraining, explainability, logging, error handling
- Designed for real OHLCV input, ready for production
"""

import json
import logging
import os
import warnings
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from sklearn import __version__ as SKLEARN_VERSION

# PyTorch imports for deep learning (optional)
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim

    torch_available = True
except Exception:
    torch_available = False
from sklearn.ensemble import RandomForestClassifier
from sklearn.exceptions import InconsistentVersionWarning
from sklearn.model_selection import GridSearchCV

try:
    from xgboost import XGBClassifier

    xgb_available = True
except ImportError:
    xgb_available = False

RANDOM_FOREST_MODEL_TYPE = "RandomForestClassifier"
XGB_MODEL_TYPE = "XGBClassifier"


class TrendPredictor:
    def __init__(
        self,
        model_path="trend_model.pkl",
        use_deep=False,
        use_xgb=False,
    ):
        self.name = "TrendPredictor"
        self.model_path = model_path
        self.use_deep = use_deep
        self.use_xgb = use_xgb and xgb_available
        self.model: Optional[object] = None
        self.is_trained = False
        self.deep_model = None
        self.deep_optimizer = None
        self.deep_loss_fn = None
        self.feature_names = []
        self.federated_global_model = None
        self.last_federated_hint = {
            "available": False,
            "applied": False,
            "reason": "uninitialized",
        }
        self._load_model()
        if self.use_deep:

            class DeepTrendNet(nn.Module):
                def __init__(self, input_dim):
                    super().__init__()
                    self.lstm = nn.LSTM(input_dim, 32, batch_first=True)
                    self.fc1 = nn.Linear(32, 16)
                    self.fc2 = nn.Linear(16, 3)

                def forward(self, x):
                    # x: (batch, seq, features)
                    _, (h_n, _) = self.lstm(x)
                    x = torch.relu(self.fc1(h_n[-1]))
                    x = self.fc2(x)
                    return x

            self.deep_model = DeepTrendNet(input_dim=10)
            self.deep_optimizer = optim.Adam(self.deep_model.parameters(), lr=0.001)
            self.deep_loss_fn = nn.CrossEntropyLoss()

    def _extract_features(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        # Advanced feature engineering: multi-timeframe, volatility, volume,
        # momentum, etc.
        df = ohlcv.copy()
        features = pd.DataFrame(index=df.index)
        # Price-based features
        features["sma_7"] = df["close"].rolling(window=7).mean()
        features["ema_7"] = df["close"].ewm(span=7, adjust=False).mean()
        features["std_7"] = df["close"].rolling(window=7).std()
        # RSI
        delta = df["close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / (avg_loss + 1e-9)
        features["rsi_14"] = 100 - (100 / (1 + rs))
        # Volatility
        features["atr_14"] = (df["high"] - df["low"]).rolling(window=14).mean()
        # Volume features
        features["vol_sma_7"] = df["volume"].rolling(window=7).mean()
        features["vol_std_7"] = df["volume"].rolling(window=7).std()
        # Momentum
        features["momentum_7"] = df["close"] - df["close"].shift(7)
        # Price change
        features["pct_change_1"] = df["close"].pct_change(1)
        # Support/resistance (rolling min/max)
        features["support_14"] = df["low"].rolling(window=14).min()
        features["resistance_14"] = (df["high"]).rolling(window=14).max()
        # Drop rows with NaN (from rolling)
        features = features.dropna()
        self.feature_names = features.columns.tolist()
        return features

    def hyperparameter_tune(self, X, y):
        # Grid search for best RandomForest or XGBoost params
        if self.use_xgb and xgb_available:
            param_grid = {
                "n_estimators": [50, 100, 200],
                "max_depth": [3, 5, 7],
            }
            grid = GridSearchCV(
                XGBClassifier(eval_metric="mlogloss", use_label_encoder=False),
                param_grid,
                cv=3,
            )
        else:
            param_grid = {
                "n_estimators": [50, 100, 200],
                "max_depth": [3, 5, 7],
            }
            grid = GridSearchCV(RandomForestClassifier(), param_grid, cv=3)
        grid.fit(X, y)
        self.model = grid.best_estimator_
        self.is_trained = True
        logging.info(f"TrendPredictor: Best params {grid.best_params_}")
        return grid.best_params_

    def train_deep(self, X, y, epochs=10):
        # LSTM expects 3D input: (batch, seq, features)
        X = np.array(X, dtype=np.float32)
        y = np.array(y, dtype=np.int64)
        X_tensor = torch.from_numpy(X).unsqueeze(1)  # (batch, seq=1, features)
        y_tensor = torch.from_numpy(y)
        self.deep_model.train()
        for epoch in range(epochs):
            self.deep_optimizer.zero_grad()
            outputs = self.deep_model(X_tensor)
            loss = self.deep_loss_fn(outputs, y_tensor)
            loss.backward()
            self.deep_optimizer.step()
        self.is_trained = True

    def retrain(self, X_new, y_new):
        # Retrain model on new data
        if self.use_deep and self.deep_model:
            self.train_deep(X_new, y_new, epochs=3)
        elif self.model:
            self.model.fit(X_new, y_new)
            self.is_trained = True
            self._save_model()
        return None

    def fit(self, ohlcv: pd.DataFrame, neutral_return_deadzone: float = 0.001):
        # Production-grade fit: advanced features, robust ML, logging,
        # error handling
        try:
            features = self._extract_features(ohlcv)
            close = ohlcv.loc[features.index, "close"]
            neutral_return_deadzone = float(neutral_return_deadzone)
            if not np.isfinite(neutral_return_deadzone):
                neutral_return_deadzone = 0.001
            neutral_return_deadzone = max(0.0, neutral_return_deadzone)
            # Label: 1=UP, -1=DOWN, 0=SIDE for economically small forward moves.
            fwd_ret = (close.shift(-1) - close) / close
            labels = np.where(
                fwd_ret > neutral_return_deadzone,
                1,
                np.where(fwd_ret < -neutral_return_deadzone, -1, 0),
            )[:-1]
            features = features.iloc[:-1]
            if self.use_deep and self.deep_model:
                self.train_deep(features.values, labels, epochs=10)
            else:
                if self.use_xgb and xgb_available:
                    self.model = XGBClassifier(
                        n_estimators=100,
                        eval_metric="mlogloss",
                        use_label_encoder=False,
                    )
                else:
                    self.model = RandomForestClassifier(
                        n_estimators=100, random_state=42
                    )
                self.model.fit(features.values, labels)
                self.is_trained = True
                self._save_model()
                metadata_path = self._metadata_path()
                if metadata_path.exists():
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    if isinstance(metadata, dict):
                        metadata["neutral_return_deadzone"] = neutral_return_deadzone
                        metadata_path.write_text(
                            json.dumps(metadata, sort_keys=True),
                            encoding="utf-8",
                        )
            logging.info(
                "TrendPredictor: model trained on %d samples, features: %s",
                len(features),
                self.feature_names,
            )
        except Exception as e:
            logging.error(f"TrendPredictor: Training failed: {e}")

    def predict(self, ohlcv: pd.DataFrame):
        # Predict trend direction: ↑, ↓, →
        if not self.is_trained or (self.model is None and self.deep_model is None):
            logging.warning("TrendPredictor: model not trained; using fallback")
            if ohlcv is None or len(ohlcv) < 2:
                return ""
            if ohlcv["close"].iloc[-1] > ohlcv["close"].iloc[-2]:
                return ""
            elif ohlcv["close"].iloc[-1] < ohlcv["close"].iloc[-2]:
                return ""
            else:
                return ""
        features = self._extract_features(ohlcv)
        if len(features) == 0:
            return "→"
        last_feat = features.iloc[[-1]].values
        if self.use_deep and self.deep_model:
            last_feat = last_feat.astype(np.float32)
            last_feat_tensor = torch.from_numpy(last_feat).unsqueeze(1)
            self.deep_model.eval()
            with torch.no_grad():
                output = self.deep_model(last_feat_tensor)
                pred = torch.argmax(output, dim=1).item()
        else:
            pred = self.model.predict(last_feat)[0]
        if pred == 1:
            return "↑"
        elif pred == -1:
            return "↓"
        else:
            return "→"

    def predict_trend(self, ohlcv: pd.DataFrame) -> str:
        # Predict trend: "UP", "DOWN", "SIDE" (production-grade, explainable)
        if (
            not self.is_trained
            or (self.model is None and self.deep_model is None)
            or len(ohlcv) < 20
        ):
            self.last_federated_hint = {
                "available": False,
                "applied": False,
                "reason": "model_not_ready",
            }
            return "SIDE"
        features = self._extract_features(ohlcv)
        if len(features) == 0:
            self.last_federated_hint = {
                "available": False,
                "applied": False,
                "reason": "insufficient_features",
            }
            return "SIDE"
        last_feat = features.iloc[[-1]].values
        if self.use_deep and self.deep_model:
            last_feat_tensor = torch.from_numpy(last_feat.astype(np.float32)).unsqueeze(
                1
            )
            self.deep_model.eval()
            with torch.no_grad():
                output = self.deep_model(last_feat_tensor)
                pred = torch.argmax(output, dim=1).item()
        else:
            pred = self.model.predict(last_feat)[0]
        pred, hint_info = self._apply_federated_direction_hint(int(pred), ohlcv)
        self.last_federated_hint = hint_info
        if pred == 1:
            return "UP"
        elif pred == -1:
            return "DOWN"
        else:
            return "SIDE"

    def _apply_federated_direction_hint(self, pred: int, ohlcv: pd.DataFrame):
        hint = {
            "available": False,
            "applied": False,
            "reason": "not_neutral_base_prediction",
            "base_pred": int(pred),
            "final_pred": int(pred),
            "direction": None,
            "threshold": None,
            "relative_diff": None,
            "last_close": None,
            "federated_model": None,
        }
        if pred != 0:
            return pred, hint
        try:
            from fl.training import normalize_global_model

            global_model = normalize_global_model(self.federated_global_model)
            if not isinstance(global_model, dict):
                hint["reason"] = "federated_model_unavailable"
                return pred, hint
            global_value = float(global_model.get("model"))
            hint["available"] = True
            hint["federated_model"] = global_value
        except Exception:
            hint["reason"] = "federated_model_invalid"
            return pred, hint
        try:
            last_close = float(ohlcv["close"].iloc[-1])
            hint["last_close"] = last_close
        except Exception:
            hint["reason"] = "last_close_unavailable"
            return pred, hint
        if last_close == 0.0:
            hint["reason"] = "last_close_zero"
            return pred, hint
        try:
            rel_threshold = float(
                os.environ.get("FL_TREND_OVERRIDE_REL_THRESH", "0.01")
            )
        except Exception:
            rel_threshold = 0.01
        rel_threshold = max(0.0, rel_threshold)
        hint["threshold"] = rel_threshold
        rel_diff = (global_value - last_close) / abs(last_close)
        hint["relative_diff"] = rel_diff
        if rel_diff > rel_threshold:
            hint["applied"] = True
            hint["direction"] = "UP"
            hint["reason"] = "federated_override_up"
            hint["final_pred"] = 1
            return 1, hint
        if rel_diff < -rel_threshold:
            hint["applied"] = True
            hint["direction"] = "DOWN"
            hint["reason"] = "federated_override_down"
            hint["final_pred"] = -1
            return -1, hint
        hint["reason"] = "below_threshold"
        return pred, hint

    def get_last_federated_hint(self) -> dict:
        return dict(self.last_federated_hint or {})

    def explain(self, ohlcv: pd.DataFrame) -> dict:
        # Explain prediction (feature importances, last values)
        features = self._extract_features(ohlcv)
        if len(features) == 0 or not self.is_trained:
            return {"explanation": "Model not trained or insufficient data."}
        last_feat = features.iloc[[-1]].values
        importances = None
        if self.model and hasattr(self.model, "feature_importances_"):
            feat_imp = self.model.feature_importances_
            importances = dict(zip(self.feature_names, feat_imp))
        return {
            "features": dict(zip(self.feature_names, last_feat.flatten())),
            "importances": importances,
            "prediction": self.predict_trend(ohlcv),
        }

    def federated_update(
        self,
        local_model,
        holdout=None,
        degrade_tol=0.0,
        outlier_sigma=5.0,
        clip_outliers=True,
    ):
        """
        Apply a federated proposal only through the FL gating path.
        Args:
            local_model: Normalized FL proposal dict or scalar model value.
        """
        from fl.training import apply_gating, normalize_global_model

        prev_global = normalize_global_model(self.federated_global_model)
        proposed_global = normalize_global_model(local_model)
        gated_global = apply_gating(
            prev_global,
            proposed_global,
            holdout=holdout,
            degrade_tol=degrade_tol,
            outlier_sigma=outlier_sigma,
            clip_outliers=clip_outliers,
        )
        self.federated_global_model = gated_global
        if proposed_global is None:
            logging.info(
                "TrendPredictor: federated update skipped (unsupported payload)."
            )
            return self.federated_global_model
        if gated_global != prev_global:
            logging.info("TrendPredictor: Federated update complete.")
        else:
            logging.info("TrendPredictor: Federated update gated or unchanged.")
        return self.federated_global_model

    def _metadata_path(self) -> Path:
        return Path(f"{self.model_path}.meta.json")

    def _expected_model_type(self) -> str:
        return XGB_MODEL_TYPE if self.use_xgb else RANDOM_FOREST_MODEL_TYPE

    def _model_metadata(self) -> dict:
        return {
            "sklearn_version": SKLEARN_VERSION,
            "model_type": type(self.model).__name__,
        }

    def _write_model_metadata(self) -> None:
        self._metadata_path().write_text(
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
        expected_type = self._expected_model_type()
        if metadata is None:
            return "metadata_missing_or_invalid"
        if str(metadata.get("sklearn_version") or "") != SKLEARN_VERSION:
            return (
                "sklearn_version_mismatch:"
                f"{metadata.get('sklearn_version')}!={SKLEARN_VERSION}"
            )
        if str(metadata.get("model_type") or "") != expected_type:
            return (
                "model_type_mismatch:"
                f"{metadata.get('model_type')}!={expected_type}"
            )
        return None

    def _reject_persisted_model(self, reason: str) -> None:
        self.model = None
        self.is_trained = False
        logging.warning(
            "TrendPredictor: ignored incompatible sklearn model at %s (%s).",
            self.model_path,
            reason,
        )

    def _save_model(self):
        if self.model is not None:
            joblib.dump(self.model, self.model_path)
            self._write_model_metadata()
            logging.info(f"TrendPredictor: model saved to {self.model_path}")

    def _load_model(self):
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
            loaded_type = type(loaded_model).__name__
            expected_type = self._expected_model_type()
            if loaded_type != expected_type:
                self._reject_persisted_model(
                    f"loaded_model_type_mismatch:{loaded_type}!={expected_type}"
                )
                return
            self.model = loaded_model
            self.is_trained = True
            logging.info(
                "TrendPredictor: model loaded from %s",
                self.model_path,
            )
        except Exception:
            self.model = None
            self.is_trained = False
