import math

from fl.runner import run_fl_round
from fl.training import (
    train_local_model,
    aggregate_models,
    normalize_global_model,
    apply_gating,
)


def test_train_local_model_empty():
    assert train_local_model([]) == {"model": None}


def test_train_local_model_normal():
    assert train_local_model([1.0, 3.0, 5.0]) == {"model": 3.0}


def test_aggregate_models_empty():
    assert aggregate_models([]) is None


def test_aggregate_models_with_invalid_models():
    assert aggregate_models([{"model": None}, {"model": None}]) is None


def test_aggregate_models_average():
    assert aggregate_models([{"model": 1.0}, {"model": 3.0}, {"model": 5.0}]) == {"model": 3.0}


def test_normalize_global_model_none():
    assert normalize_global_model(None) is None
    assert normalize_global_model({"model": None}) is None


def test_normalize_global_model_invalid():
    assert normalize_global_model({"model": "abc"}) is None
    assert normalize_global_model({"model": float('nan')}) is None
    assert normalize_global_model({"model": float('inf')}) is None


def test_apply_gating_accepts_good_update():
    prev = {"model": 1.0}
    new = {"model": 1.1}
    holdout = [1.0, 1.2]
    output = apply_gating(prev, new, holdout=holdout, degrade_tol=0.1, outlier_sigma=10.0)
    assert output == {"model": 1.1}


def test_apply_gating_reject_degrading():
    prev = {"model": 1.0}
    new = {"model": 10.0}
    holdout = [1.0, 1.1, 0.9]
    output = apply_gating(prev, new, holdout=holdout, degrade_tol=0.0, outlier_sigma=1000.0)
    assert output == prev


def test_apply_gating_outlier_clip():
    prev = {"model": 1.0}
    new = {"model": 20.0}
    holdout = [1.0, 1.1, 0.9]
    output = apply_gating(prev, new, holdout=holdout, outlier_sigma=1.0, clip_outliers=True)
    # should clip near 1.0 + 1*std
    std = math.sqrt(sum((x-1)**2 for x in holdout)/len(holdout))
    assert output["model"] <= 1.0 + std + 1e-9


def test_apply_gating_outlier_reject_when_no_clip():
    prev = {"model": 1.0}
    new = {"model": 20.0}
    holdout = [1.0, 1.1, 0.9]
    output = apply_gating(prev, new, holdout=holdout, outlier_sigma=1.0, clip_outliers=False)
    assert output == prev


def test_run_fl_round_integration():
    clients = [{"data": [1.0, 2.0]}, {"data": [3.0, 4.0]}]
    base = {"model": 0.0}
    flipped = run_fl_round(clients, base, holdout=[2.0, 3.0], outlier_sigma=100.0)
    assert isinstance(flipped, dict)
    assert "model" in flipped
