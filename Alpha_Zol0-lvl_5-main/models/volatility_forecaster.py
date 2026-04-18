# ✅ Completed by ZoL0-FIXER — 2025-07-29
# Description: Completed VolatilityForecaster with full deep/XGB/RandomForest
# logic, docstrings, type hints, and robust
# bootstrapping. No placeholders remain.
# volatility_forecaster.py – Regresja zmienności


import json
import logging
import warnings
from pathlib import Path

import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim
from sklearn import __version__ as SKLEARN_VERSION
from sklearn.exceptions import InconsistentVersionWarning

logger = logging.getLogger(__name__)

XGB_MODEL_TYPE = "XGBRegressor"
RANDOM_FOREST_MODEL_TYPE = "RandomForestRegressor"


class VolatilityForecaster:
    def __init__(
        self,
        use_deep: bool = False,
        model_path: str = "vol_model.pkl",
        use_xgb: bool = True,
    ):
        """
        Initialize the VolatilityForecaster.
        Args:
            use_deep: Whether to use a deep learning model.
            model_path: Path to save/load the model.
            use_xgb: Whether to use XGBoost (else RandomForest).
        """
        self.name = "VolatilityForecaster"
        self.use_deep = use_deep
        self.model_path = model_path
        self.model = None
        self.is_trained = False
        self.use_xgb = use_xgb
        if use_deep:

            class DeepVolNet(nn.Module):
                def __init__(self):
                    super().__init__()
                    self.fc1 = nn.Linear(3, 32)
                    self.dropout1 = nn.Dropout(0.2)
                    self.fc2 = nn.Linear(32, 16)
                    self.fc3 = nn.Linear(16, 1)

                def forward(self, x):
                    x = torch.relu(self.fc1(x))
                    x = self.dropout1(x)
                    x = torch.relu(self.fc2(x))
                    x = self.fc3(x)
                    return x

            self.deep_model = DeepVolNet()
            self.deep_optimizer = optim.Adam(self.deep_model.parameters(), lr=0.001)
            self.deep_loss_fn = nn.MSELoss()
        else:
            self.load_model()

    def _metadata_path(self) -> Path:
        return Path(f"{self.model_path}.meta.json")

    def _expected_model_type(self) -> str:
        return XGB_MODEL_TYPE if self.use_xgb else RANDOM_FOREST_MODEL_TYPE

    def _current_xgboost_version(self) -> str | None:
        try:
            import xgboost
        except Exception:
            return None
        return str(xgboost.__version__)

    def _model_metadata(self) -> dict:
        model_type = type(self.model).__name__
        metadata = {"model_type": model_type}
        if model_type == XGB_MODEL_TYPE:
            xgboost_version = self._current_xgboost_version()
            if xgboost_version is not None:
                metadata["xgboost_version"] = xgboost_version
        elif model_type == RANDOM_FOREST_MODEL_TYPE:
            metadata["sklearn_version"] = SKLEARN_VERSION
        return metadata

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
        if str(metadata.get("model_type") or "") != expected_type:
            return (
                "model_type_mismatch:"
                f"{metadata.get('model_type')}!={expected_type}"
            )
        if expected_type == XGB_MODEL_TYPE:
            xgboost_version = self._current_xgboost_version()
            if xgboost_version is None:
                return "xgboost_unavailable"
            if str(metadata.get("xgboost_version") or "") != xgboost_version:
                return (
                    "xgboost_version_mismatch:"
                    f"{metadata.get('xgboost_version')}!={xgboost_version}"
                )
        elif str(metadata.get("sklearn_version") or "") != SKLEARN_VERSION:
            return (
                "sklearn_version_mismatch:"
                f"{metadata.get('sklearn_version')}!={SKLEARN_VERSION}"
            )
        return None

    def _reject_persisted_model(self, reason: str) -> None:
        self.model = None
        self.is_trained = False
        logger.warning(
            "VolatilityForecaster: ignored incompatible model at %s (%s).",
            self.model_path,
            reason,
        )

    def train_model(self, X, y) -> None:
        """
        Train the volatility model (deep, XGB, or RandomForest).
        Args:
            X: Features (list or np.ndarray)
            y: Targets (list or np.ndarray)
        """
        import joblib

        if self.use_deep and hasattr(self, "deep_model"):
            import numpy as np

            X = np.array(X, dtype=np.float32)
            y = np.array(y, dtype=np.float32)
            X_tensor = torch.from_numpy(X)
            y_tensor = torch.from_numpy(y).unsqueeze(1)
            self.deep_model.train()
            for epoch in range(100):
                self.deep_optimizer.zero_grad()
                output = self.deep_model(X_tensor)
                loss = self.deep_loss_fn(output, y_tensor)
                loss.backward()
                self.deep_optimizer.step()
                if epoch % 20 == 0:
                    logger.info(f"[DeepVolNet] Epoch {epoch} Loss: {loss.item():.4f}")
            self.is_trained = True
            torch.save(self.deep_model.state_dict(), self.model_path + ".pt")
        elif self.use_xgb:
            try:
                from xgboost import XGBRegressor
            except ImportError:
                logger.error("xgboost is not installed.")
                raise
            self.model = XGBRegressor(n_estimators=100)
            self.model.fit(X, y)
            self.is_trained = True
            joblib.dump(self.model, self.model_path)
            self._write_model_metadata()
        else:
            from sklearn.ensemble import RandomForestRegressor

            self.model = RandomForestRegressor(n_estimators=100)
            self.model.fit(X, y)
            self.is_trained = True
            joblib.dump(self.model, self.model_path)
            self._write_model_metadata()

    def load_model(self) -> None:
        """
        Load the trained model from disk.
        """
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
            loaded_type = type(loaded_model).__name__
            expected_type = self._expected_model_type()
            if loaded_type != expected_type:
                self._reject_persisted_model(
                    f"loaded_model_type_mismatch:{loaded_type}!={expected_type}"
                )
                return
            self.model = loaded_model
            self.is_trained = True
        except Exception as exc:
            self.model = None
            self.is_trained = False
            logger.warning(
                "VolatilityForecaster: model load skipped path=%s error=%s",
                self.model_path,
                exc,
            )

    def extract_features(self, ohlcv) -> list:
        """
        Extract features for volatility prediction from OHLCV data.
        Args:
            ohlcv: DataFrame or list of dicts with OHLCV data.
        Returns:
            List of features [std, atr, bollinger].
        """
        # Convert list of dicts to DataFrame if needed
        if isinstance(ohlcv, list):
            ohlcv = pd.DataFrame(ohlcv)
        std = (
            ohlcv["close"].rolling(window=7).std().iloc[-1] if len(ohlcv) >= 7 else 0.0
        )
        high = ohlcv["high"] if "high" in ohlcv else ohlcv["close"]
        low = ohlcv["low"] if "low" in ohlcv else ohlcv["close"]
        close = ohlcv["close"]
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=7).mean().iloc[-1] if len(tr) >= 7 else 0.0
        sma = close.rolling(window=7).mean().iloc[-1] if len(close) >= 7 else 0.0
        boll = (std / sma) if sma != 0 else 0
        return [std, atr, boll]

    def forecast_volatility(self, ohlcv) -> float:
        """
        Predict volatility for the given OHLCV data.
        Args:
            ohlcv: DataFrame or list of dicts with OHLCV data.
        Returns:
            Predicted volatility (float).
        """
        # Convert list of dicts to DataFrame if needed
        if isinstance(ohlcv, list):
            ohlcv = pd.DataFrame(ohlcv)
        feats = self.extract_features(ohlcv)
        if self.use_deep and self.deep_model:
            import numpy as np
            import torch

            self.deep_model.eval()
            feats_tensor = torch.from_numpy(
                np.array(feats, dtype=np.float32)
            ).unsqueeze(0)
            with torch.no_grad():
                output = self.deep_model(feats_tensor)
                return float(output.item())
        elif self.model and self.is_trained:
            try:
                return float(self.model.predict([feats])[0])
            except Exception:
                logger.error("VolatilityForecaster: model prediction error.")
                raise RuntimeError("VolatilityForecaster: Model prediction failed.")
        else:
            # Bootstrapping: train a default model on the fly
            # using current OHLCV data

            logger.warning(
                "VolatilityForecaster: No trained model found. "
                "Bootstrapping with current OHLCV data."
            )
            # Use rolling std as target for quick fit
            if len(ohlcv) >= 8:
                X = []
                y = []
                for i in range(7, len(ohlcv)):
                    window = ohlcv.iloc[i - 7 : i + 1]
                    feats_i = self.extract_features(window)
                    X.append(feats_i)
                    y.append(window["close"].rolling(window=7).std().iloc[-1])
                if len(X) > 0:
                    self.train_model(X, y)
                    self.is_trained = True
                    return float(self.model.predict([feats])[0])
                else:
                    logger.error(
                        ("VolatilityForecaster: Not enough data to " "bootstrap model.")
                    )
                    return 0.0
            else:
                logger.error(
                    (
                        "VolatilityForecaster: Not enough OHLCV data to "
                        "bootstrap model."
                    )
                )
                return 0.0
