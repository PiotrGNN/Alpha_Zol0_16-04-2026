# Federated learning gating tests
import math
import logging

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
