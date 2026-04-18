"""
ai_utils.py – Robust AI utility functions for feature extraction,
normalization, train/test split, and RSI.
Fully production-ready and PEP8-compliant.
"""

import logging
import numpy as np
import pandas as pd
from typing import List, Tuple
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import (
    train_test_split as sk_train_test_split,
)

logger = logging.getLogger(__name__)


def ohlcv_to_vector(ohlcv: List[float]) -> List[float]:
    """
    Convert OHLCV list to a normalized vector for ML models.
    Args:
        ohlcv (List[float]): [open, high, low, close, volume]
    Returns:
        List[float]: Normalized vector
    """
    if not ohlcv or len(ohlcv) < 5:
        logger.error("ohlcv_to_vector: Input must have at least 5 elements.")
        raise ValueError("ohlcv_to_vector: Input must have at least 5 elements.")
    arr = np.array(ohlcv, dtype=float)
    norm = (arr - arr.mean()) / (arr.std() + 1e-8)
    logger.debug(f"ohlcv_to_vector: {norm.tolist()}")
    return norm.tolist()


def extract_features(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """
    Extracts advanced features from OHLCV DataFrame (multi-timeframe,
    volatility, momentum, etc.)
    Args:
        ohlcv (pd.DataFrame): DataFrame with columns [
            'open', 'high', 'low', 'close', 'volume'
        ]
    Returns:
        pd.DataFrame: DataFrame with extracted features
    """
    if ohlcv is None or ohlcv.empty:
        logger.error("extract_features: Input DataFrame is empty.")
        return pd.DataFrame()
    df = ohlcv.copy()
    # Basic features
    df["returns"] = df["close"].pct_change().fillna(0)
    df["volatility"] = df["returns"].rolling(window=10).std().fillna(0)
    df["momentum"] = df["close"] - df["close"].shift(10).fillna(0)
    df["sma_5"] = df["close"].rolling(window=5).mean().bfill()
    df["sma_10"] = df["close"].rolling(window=10).mean().bfill()
    df["ema_5"] = df["close"].ewm(span=5, adjust=False).mean()
    df["ema_10"] = df["close"].ewm(span=10, adjust=False).mean()
    df["rsi_14"] = compute_rsi(df["close"], window=14)
    logger.debug(f"extract_features: columns={df.columns.tolist()}")
    return df


def compute_rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """
    Compute Relative Strength Index (RSI) for a price series.
    """
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / (loss + 1e-8)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(0)


def normalize_features(X: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize features using StandardScaler.
    Args:
        X (pd.DataFrame): Feature DataFrame
    Returns:
        pd.DataFrame: Normalized DataFrame
    """
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    logger.debug("normalize_features: Features normalized.")
    return pd.DataFrame(X_scaled, columns=X.columns, index=X.index)


def train_test_split(
    X: np.ndarray, y: np.ndarray, test_size: float = 0.2
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Split data into train and test sets.
    Args:
        X (np.ndarray): Features
        y (np.ndarray): Targets
        test_size (float): Fraction for test set
    Returns:
        Tuple: X_train, X_test, y_train, y_test
    """
    X_train, X_test, y_train, y_test = sk_train_test_split(
        X, y, test_size=test_size, random_state=42
    )
    logger.info(
        "train_test_split: %d train, %d test samples.",
        len(X_train),
        len(X_test),
    )
    return X_train, X_test, y_train, y_test
