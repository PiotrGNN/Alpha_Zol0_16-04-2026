"""
# ✅ Completed by ZoL0-FIXER — 2025-07-29
# Description: Completed MarketForecaster with robust model training,
# prediction, feature extraction, and docstrings. Production-ready.
# market_forecaster.py – MarketForecaster: przewidywanie kierunku rynku
"""

import logging
from typing import Dict, List
import numpy as np


class MarketForecaster:
    def __init__(
        self,
        model_path: str = "market_model.pkl",
        use_xgb: bool = True,
    ):
        """
        Initialize the MarketForecaster.
        Args:
            model_path: Path to save/load the model.
            use_xgb: Whether to use XGBoost (else RandomForest).
        """
        self.model_path = model_path
        self.use_xgb = use_xgb
        self.model = None
        self.trained = False
        self.logger = logging.getLogger(__name__)
        self.load_model()

    def train_model(self, X: List[List[float]], y: List[float]) -> None:
        """
        Train the market forecasting model.
        Args:
            X: List of feature vectors.
            y: List of target values.
        """
        import joblib

        if self.use_xgb:
            try:
                from xgboost import XGBRegressor
            except ImportError:
                self.logger.error("xgboost is not installed.")
                raise
            self.model = XGBRegressor(n_estimators=100)
        else:
            from sklearn.ensemble import RandomForestRegressor

            self.model = RandomForestRegressor(n_estimators=100)
        self.model.fit(X, y)
        self.trained = True
        joblib.dump(self.model, self.model_path)
        self.logger.info("MarketForecaster: Model trained and saved.")

    def load_model(self) -> None:
        """
        Load the trained model from disk.
        """
        import joblib

        try:
            self.model = joblib.load(self.model_path)
            self.trained = True
            self.logger.info("MarketForecaster: Model loaded.")
        except Exception:
            self.model = None
            self.trained = False
            self.logger.warning("MarketForecaster: No trained model found.")

    def predict(self, features: List[float]) -> float:
        """
        Predict the market value given features.
        Args:
            features: Feature vector.
        Returns:
            Predicted value (float).
        """
        if not self.trained or self.model is None:
            try:
                self.load_model()
            except Exception as e:
                self.logger.error(
                    "MarketForecaster: model not loaded or trained: %s", e
                )
                raise RuntimeError("MarketForecaster: No trained model available.")
        pred = self.model.predict([features])[0]
        self.logger.info(f"MarketForecaster: prediction={pred}")
        return pred

    def extract_features(self, ohlcv_seq: List[Dict]) -> List[float]:
        """
        Extracts features for market forecasting from OHLCV sequence.
        Args:
            ohlcv_seq: List of OHLCV dicts (with optional sentiment).
        Returns:
            List of features: [volatility, trend, sentiment].
        """
        if not ohlcv_seq or len(ohlcv_seq) < 2:
            self.logger.warning(
                "MarketForecaster: Not enough OHLCV data for " "feature extraction."
            )
            return [0.0, 0.0, 0.0]
        closes = np.array([x.get("close", 0) for x in ohlcv_seq])
        volatility = (
            float(np.std(closes[-10:])) if len(closes) >= 10 else float(np.std(closes))
        )
        trend = float(closes[-1] - closes[0]) / (abs(closes[0]) + 1e-8)
        sentiment = float(np.mean([x.get("sentiment", 0) for x in ohlcv_seq]))
        self.logger.debug(
            "MarketForecaster: features extracted: "
            f"volatility={volatility}, "
            f"trend={trend}, "
            f"sentiment={sentiment}"
        )
        return [volatility, trend, sentiment]
