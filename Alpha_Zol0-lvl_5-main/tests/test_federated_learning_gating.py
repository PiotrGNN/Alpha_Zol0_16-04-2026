# Federated learning gating tests
import math
import logging

import pandas as pd

from fl.runner import run_fl_round
from models.trend_predictor import TrendPredictor


def _std(values):
    mean = sum(values) / len(values)
    var = sum((x - mean) ** 2 for x in values) / len(values)
    return math.sqrt(var)


def test_reject_degrading_update(caplog):
    caplog.set_level(logging.WARNING)
    global_model = {"model": 0.0}
    holdout = [0.1, -0.1, 0.0, 0.05]
    clients = [{"data": [10.0, 10.0, 10.0]}]

    res = run_fl_round(
        clients,
        global_model,
        holdout=holdout,
        degrade_tol=0.0,
        outlier_sigma=1000.0,
    )

    assert res == global_model
    assert "FL update rejected (degrading)" in caplog.text


def test_reject_or_clip_outlier_update(caplog):
    caplog.set_level(logging.WARNING)
    global_model = {"model": 10.0}
    holdout = [9.0, 10.0, 11.0, 10.0]
    clients = [{"data": [100.0, 100.0, 100.0]}]

    outlier_sigma = 1.0
    limit = outlier_sigma * _std(holdout)
    res = run_fl_round(
        clients,
        global_model,
        holdout=holdout,
        outlier_sigma=outlier_sigma,
        clip_outliers=True,
        degrade_tol=0.0,
    )

    assert "FL update rejected/clipped (outlier)" in caplog.text
    assert abs(res["model"] - global_model["model"]) <= limit + 1e-9


def test_trend_predictor_federated_update_uses_gating(caplog):
    caplog.set_level(logging.INFO)
    predictor = TrendPredictor()
    holdout = [9.0, 10.0, 11.0, 10.0]

    first_update = predictor.federated_update({"model": 10.0}, holdout=holdout)
    second_update = predictor.federated_update(
        {"model": 100.0},
        holdout=holdout,
        outlier_sigma=1.0,
        clip_outliers=False,
    )

    assert first_update == {"model": 10.0}
    assert second_update == first_update
    assert predictor.federated_global_model == first_update


def test_predict_trend_uses_federated_hint_for_neutral_prediction(monkeypatch):
    predictor = TrendPredictor()
    predictor.is_trained = True

    class _NeutralModel:
        def predict(self, _arr):
            return [0]

    predictor.model = _NeutralModel()
    predictor.use_deep = False
    predictor.deep_model = None
    predictor.federated_global_model = {"model": 105.0}
    monkeypatch.setenv("FL_TREND_OVERRIDE_REL_THRESH", "0.01")

    def _fake_extract(_ohlcv):
        return pd.DataFrame({"f": [1.0]}, index=[0])

    predictor._extract_features = _fake_extract
    ohlcv = pd.DataFrame(
        {
            "close": [100.0] * 25,
            "high": [101.0] * 25,
            "low": [99.0] * 25,
            "volume": [1.0] * 25,
        }
    )

    assert predictor.predict_trend(ohlcv) == "UP"


def test_predict_trend_federated_hint_respects_threshold(monkeypatch):
    predictor = TrendPredictor()
    predictor.is_trained = True

    class _NeutralModel:
        def predict(self, _arr):
            return [0]

    predictor.model = _NeutralModel()
    predictor.use_deep = False
    predictor.deep_model = None
    predictor.federated_global_model = {"model": 100.2}
    monkeypatch.setenv("FL_TREND_OVERRIDE_REL_THRESH", "0.01")

    def _fake_extract(_ohlcv):
        return pd.DataFrame({"f": [1.0]}, index=[0])

    predictor._extract_features = _fake_extract
    ohlcv = pd.DataFrame(
        {
            "close": [100.0] * 25,
            "high": [101.0] * 25,
            "low": [99.0] * 25,
            "volume": [1.0] * 25,
        }
    )

    assert predictor.predict_trend(ohlcv) == "SIDE"


def test_predict_trend_exposes_last_federated_hint_metadata(monkeypatch):
    predictor = TrendPredictor()
    predictor.is_trained = True

    class _NeutralModel:
        def predict(self, _arr):
            return [0]

    predictor.model = _NeutralModel()
    predictor.use_deep = False
    predictor.deep_model = None
    predictor.federated_global_model = {"model": 95.0}
    monkeypatch.setenv("FL_TREND_OVERRIDE_REL_THRESH", "0.01")

    def _fake_extract(_ohlcv):
        return pd.DataFrame({"f": [1.0]}, index=[0])

    predictor._extract_features = _fake_extract
    ohlcv = pd.DataFrame(
        {
            "close": [100.0] * 25,
            "high": [101.0] * 25,
            "low": [99.0] * 25,
            "volume": [1.0] * 25,
        }
    )

    trend = predictor.predict_trend(ohlcv)
    hint = predictor.get_last_federated_hint()

    assert trend == "DOWN"
    assert hint["available"] is True
    assert hint["applied"] is True
    assert hint["direction"] == "DOWN"
    assert hint["reason"] == "federated_override_down"
    assert hint["base_pred"] == 0
    assert hint["final_pred"] == -1
    assert hint["threshold"] == 0.01
