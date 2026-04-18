from models.ai_utils import (
    ohlcv_to_vector,
)
from models.trend_predictor import (
    TrendPredictor,
)
from models.volatility_forecaster import (
    VolatilityForecaster,
)


def test_trend_predictor_import_does_not_disable_all_warnings():
    import subprocess
    import sys
    from pathlib import Path

    script = (
        "import warnings; "
        "import models.trend_predictor; "
        "print(int(any("
        "f[0] == 'ignore' and f[1] is None and f[2] is Warning "
        "for f in warnings.filters"
        ")))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).resolve().parents[1],
    )

    assert result.stdout.strip() == "0"


def test_trend_predictor_writes_metadata_and_compatible_model_loads(tmp_path):
    import json
    from sklearn import __version__ as sklearn_version
    from sklearn.ensemble import RandomForestClassifier

    model_path = tmp_path / "trend_model.pkl"
    predictor = TrendPredictor(model_path=str(model_path))
    predictor.model = RandomForestClassifier(n_estimators=2, random_state=42)
    predictor.model.fit([[0.0] * 10, [1.0] * 10], [0, 1])
    predictor.is_trained = True

    predictor._save_model()

    metadata = json.loads(
        (tmp_path / "trend_model.pkl.meta.json").read_text(encoding="utf-8")
    )
    assert metadata == {
        "model_type": "RandomForestClassifier",
        "sklearn_version": sklearn_version,
    }

    loaded = TrendPredictor(model_path=str(model_path))

    assert loaded.is_trained is True
    assert type(loaded.model).__name__ == "RandomForestClassifier"


def test_trend_predictor_rejects_incompatible_metadata_before_pickle_load(
    monkeypatch,
    tmp_path,
):
    import json
    import joblib
    import pytest

    model_path = tmp_path / "trend_model.pkl"
    model_path.write_bytes(b"not-a-pickle")
    (tmp_path / "trend_model.pkl.meta.json").write_text(
        json.dumps(
            {
                "model_type": "RandomForestClassifier",
                "sklearn_version": "1.8.0",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        joblib,
        "load",
        lambda _path: pytest.fail("incompatible metadata must block before load"),
    )

    predictor = TrendPredictor(model_path=str(model_path))

    assert predictor.is_trained is False
    assert predictor.model is None


def test_trend_predictor_rejects_inconsistent_version_warning(
    monkeypatch,
    tmp_path,
):
    import json
    import warnings
    import joblib
    from sklearn import __version__ as sklearn_version
    from sklearn.exceptions import InconsistentVersionWarning

    model_path = tmp_path / "trend_model.pkl"
    model_path.write_bytes(b"pickle-bytes")
    (tmp_path / "trend_model.pkl.meta.json").write_text(
        json.dumps(
            {
                "model_type": "RandomForestClassifier",
                "sklearn_version": sklearn_version,
            }
        ),
        encoding="utf-8",
    )

    def fake_load(_path):
        warnings.warn(
            InconsistentVersionWarning(
                estimator_name="RandomForestClassifier",
                current_sklearn_version=sklearn_version,
                original_sklearn_version="1.8.0",
            )
        )
        return object()

    monkeypatch.setattr(joblib, "load", fake_load)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", InconsistentVersionWarning)
        predictor = TrendPredictor(model_path=str(model_path))

    assert not [
        warning
        for warning in caught
        if isinstance(warning.message, InconsistentVersionWarning)
    ]
    assert predictor.is_trained is False
    assert predictor.model is None


def test_volatility_forecaster_writes_metadata_and_compatible_xgb_model_loads(
    tmp_path,
):
    import json
    import xgboost

    model_path = tmp_path / "vol_model.pkl"
    forecaster = VolatilityForecaster(model_path=str(model_path))

    forecaster.train_model(
        [[0.0, 0.0, 0.0], [1.0, 0.5, 0.1], [2.0, 0.7, 0.2], [3.0, 0.9, 0.3]],
        [0.1, 0.2, 0.3, 0.4],
    )

    metadata = json.loads(
        (tmp_path / "vol_model.pkl.meta.json").read_text(encoding="utf-8")
    )
    assert metadata == {
        "model_type": "XGBRegressor",
        "xgboost_version": xgboost.__version__,
    }

    loaded = VolatilityForecaster(model_path=str(model_path))

    assert loaded.is_trained is True
    assert type(loaded.model).__name__ == "XGBRegressor"


def test_volatility_forecaster_rejects_missing_metadata_before_pickle_load(
    monkeypatch,
    tmp_path,
):
    import joblib
    import pytest

    model_path = tmp_path / "vol_model.pkl"
    model_path.write_bytes(b"not-a-pickle")
    monkeypatch.setattr(
        joblib,
        "load",
        lambda _path: pytest.fail("missing metadata must block before load"),
    )

    forecaster = VolatilityForecaster(model_path=str(model_path))

    assert forecaster.is_trained is False
    assert forecaster.model is None


def test_volatility_forecaster_rejects_incompatible_metadata_before_pickle_load(
    monkeypatch,
    tmp_path,
):
    import json
    import joblib
    import pytest

    model_path = tmp_path / "vol_model.pkl"
    model_path.write_bytes(b"not-a-pickle")
    (tmp_path / "vol_model.pkl.meta.json").write_text(
        json.dumps(
            {
                "model_type": "XGBRegressor",
                "xgboost_version": "0.0.0",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        joblib,
        "load",
        lambda _path: pytest.fail("incompatible metadata must block before load"),
    )

    forecaster = VolatilityForecaster(model_path=str(model_path))

    assert forecaster.is_trained is False
    assert forecaster.model is None


def test_trend_predictor():
    import pandas as pd

    predictor = TrendPredictor()
    data_up = pd.DataFrame({"close": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]})
    data_down = pd.DataFrame({"close": [14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]})
    data_side = pd.DataFrame({"close": [5] * 14})
    assert predictor.predict_trend(data_up) in ["UP", "SIDE"]
    assert predictor.predict_trend(data_down) in ["DOWN", "SIDE"]
    assert predictor.predict_trend(data_side) == "SIDE"


def test_volatility_forecaster():
    import pandas as pd

    forecaster = VolatilityForecaster()
    data = pd.DataFrame(
        {
            "close": [1, 2, 3, 4, 5, 6, 7],
            "high": [2, 3, 4, 5, 6, 7, 8],
            "low": [0, 1, 2, 3, 4, 5, 6],
        }
    )
    # Bootstrap model if not trained
    X = [forecaster.extract_features(data)] * 10
    y = [0.1 * i for i in range(10)]
    forecaster.train_model(X, y)
    assert forecaster.forecast_volatility(data) >= 0.0
    empty = pd.DataFrame({"close": [], "high": [], "low": []})
    try:
        forecaster.forecast_volatility(empty)
    except Exception:
        pass


def test_ohlcv_to_vector():
    import pytest

    with pytest.raises(ValueError):
        ohlcv_to_vector([1, 2, 4])


def test_predict_trend():
    import pandas as pd
    from models.trend_predictor import TrendPredictor

    data = pd.DataFrame(
        {
            "close": [1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4, 5, 5],
            "high": [x + 0.5 for x in [1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4, 5, 5]],
            "low": [x - 0.5 for x in [1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4, 5, 5]],
            "timestamp": [f"2025-07-28T12:{i:02d}:00" for i in range(14)],
        }
    )
    predictor = TrendPredictor()
    trend = predictor.predict_trend(data)
    assert trend in ["UP", "DOWN", "SIDE"]


def test_forecast_volatility():
    import pandas as pd
    from models.volatility_forecaster import VolatilityForecaster

    data = pd.DataFrame(
        {
            "close": [1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2],
            "high": [x + 0.5 for x in [1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2]],
            "low": [x - 0.5 for x in [1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2]],
            "timestamp": [f"2025-07-28T12:{i:02d}:00" for i in range(14)],
        }
    )
    forecaster = VolatilityForecaster()
    # Bootstrap model if not trained
    X = [forecaster.extract_features(data)] * 10
    y = [0.1 * i for i in range(10)]
    forecaster.train_model(X, y)
    vol = forecaster.forecast_volatility(data)
    assert isinstance(vol, float)
    assert vol >= 0
