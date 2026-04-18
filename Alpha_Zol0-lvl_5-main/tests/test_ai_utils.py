import pandas as pd
import numpy as np
from models import ai_utils


def test_ohlcv_to_vector():
    ohlcv = [1, 2, 3, 4, 5]
    result = ai_utils.ohlcv_to_vector(ohlcv)
    assert isinstance(result, list)
    assert len(result) == 5
    arr = np.array(result)
    assert abs(arr.mean()) < 1e-6
    assert abs(arr.std() - 1) < 1e-6


def test_extract_features():
    df = pd.DataFrame(
        {
            "open": [1, 2],
            "high": [2, 3],
            "low": [0, 1],
            "close": [1.5, 2.5],
            "volume": [100, 200],
        }
    )
    features = ai_utils.extract_features(df)
    assert isinstance(features, pd.DataFrame)
    assert not features.empty


def test_compute_rsi():
    series = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15])
    rsi = ai_utils.compute_rsi(series)
    assert isinstance(rsi, pd.Series)
    assert len(rsi) == len(series)


def test_normalize_features():
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    norm = ai_utils.normalize_features(df)
    assert isinstance(norm, pd.DataFrame)
    assert norm.shape == df.shape
    assert abs(norm.mean().mean()) < 1e-8  # mean ~0


def test_train_test_split():
    X = np.arange(20).reshape(10, 2)
    y = np.arange(10)
    X_train, X_test, y_train, y_test = ai_utils.train_test_split(X, y, test_size=0.2)
    assert X_train.shape[0] == y_train.shape[0]
    assert X_test.shape[0] == y_test.shape[0]
    assert X_train.shape[1] == X.shape[1]
    assert X_test.shape[1] == X.shape[1]
    assert X_train.shape[0] + X_test.shape[0] == X.shape[0]
