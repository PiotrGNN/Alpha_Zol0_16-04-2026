# training.py – Federated Learning: train_local_model, aggregate_models
import logging
import math


def train_local_model(data):
    # Example: train a simple model (mean of data)
    if not data:
        return {"model": None}
    mean = sum(data) / len(data)
    return normalize_global_model({"model": mean})


def aggregate_models(models):
    # Aggregate by averaging model values
    if not models:
        return None
    values = [m["model"] for m in models if m["model"] is not None]
    if not values:
        return None
    avg = sum(values) / len(values)
    return normalize_global_model({"model": avg})


def _model_value(model):
    if model is None:
        return None
    if isinstance(model, dict):
        return model.get("model")
    return model


def normalize_global_model(model):
    value = _model_value(model)
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return {"model": value}


def _score_model(model, holdout):
    if model is None or not holdout:
        return None
    val = _model_value(model)
    if val is None:
        return None
    mse = sum((x - val) ** 2 for x in holdout) / len(holdout)
    return -mse


def _holdout_std(holdout):
    if not holdout or len(holdout) < 2:
        return None
    mean = sum(holdout) / len(holdout)
    var = sum((x - mean) ** 2 for x in holdout) / len(holdout)
    return math.sqrt(var)


def apply_gating(
    prev_global,
    new_global,
    holdout=None,
    degrade_tol=0.0,
    outlier_sigma=5.0,
    clip_outliers=True,
):
    """
    Gate FL updates:
    - reject degrading update based on holdout score
    - reject/clip outlier updates based on jump vs prev
    """
    prev_global = normalize_global_model(prev_global)
    new_global = normalize_global_model(new_global)
    if new_global is None:
        return prev_global
    prev_val = _model_value(prev_global)
    new_val = _model_value(new_global)

    # Outlier gating (jump vs previous global)
    if prev_val is not None and new_val is not None:
        limit = None
        std = _holdout_std(holdout)
        if std is not None:
            limit = outlier_sigma * std
        else:
            limit = outlier_sigma
        if limit is not None and abs(new_val - prev_val) > limit:
            logging.warning("FL update rejected/clipped (outlier)")
            if clip_outliers and limit is not None:
                clipped = prev_val + (limit if new_val > prev_val else -limit)
                return {"model": clipped}
            return prev_global

    # Degrading gating (score drop)
    if holdout:
        prev_score = _score_model(prev_global, holdout)
        new_score = _score_model(new_global, holdout)
        if (
            prev_score is not None
            and new_score is not None
            and new_score < (prev_score - degrade_tol)
        ):
            logging.warning("FL update rejected (degrading)")
            return prev_global

    return new_global
