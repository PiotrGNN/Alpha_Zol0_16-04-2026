import json
import warnings

import joblib
import pytest
from sklearn import __version__ as SKLEARN_VERSION
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.exceptions import InconsistentVersionWarning

from ai.OnlineTrainer import OnlineTrainer


def test_adaptive_weight_increases_after_positive_feedback(tmp_path):
    trainer = OnlineTrainer(model_path=str(tmp_path / "ot_model.pkl"))
    base_weight = 0.2
    initial = trainer.adaptive_vote_weight(base_weight)

    for _ in range(5):
        trainer.record_trade_outcome(
            1.0,
            predicted_side="buy",
            executed_side="buy",
        )

    boosted = trainer.adaptive_vote_weight(base_weight)
    stats = trainer.get_feedback_stats()
    assert boosted > initial
    assert stats["reward_ema"] > 0
    assert stats["hit_ema"] > 0.5


def test_adaptive_weight_is_penalized_after_loss_streak(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_WEIGHT_MIN_SCALE", "0.2")
    monkeypatch.setenv("AI_WEIGHT_MAX_SCALE", "2.0")
    monkeypatch.setenv("AI_LOSS_STREAK_CUTOFF", "2")
    trainer = OnlineTrainer(model_path=str(tmp_path / "ot_model.pkl"))
    base_weight = 0.2

    trainer.record_trade_outcome(-1.0, predicted_side="buy", executed_side="buy")
    trainer.record_trade_outcome(-1.0, predicted_side="buy", executed_side="buy")

    penalized = trainer.adaptive_vote_weight(base_weight)
    assert penalized <= base_weight * 0.2 + 1e-9
    assert trainer.get_feedback_stats()["loss_streak"] >= 2


def test_hit_ema_unchanged_when_prediction_not_used(tmp_path):
    trainer = OnlineTrainer(model_path=str(tmp_path / "ot_model.pkl"))
    before = trainer.get_feedback_stats()["hit_ema"]
    trainer.record_trade_outcome(
        1.0,
        predicted_side="buy",
        executed_side="sell",
    )
    after = trainer.get_feedback_stats()["hit_ema"]
    assert after == before


def test_update_model_writes_metadata_and_compatible_model_loads(tmp_path):
    model_path = tmp_path / "ot_model.pkl"
    trainer = OnlineTrainer(n_features=2, model_path=str(model_path))
    trainer.X = [[0, 0, 0, 0, 0], [1, 1, 1, 1, 1]]
    trainer.y = [0, 1]

    trainer.update_model()

    metadata_path = tmp_path / "ot_model.pkl.meta.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata == {
        "model_type": "GradientBoostingClassifier",
        "sklearn_version": SKLEARN_VERSION,
    }

    loaded = OnlineTrainer(n_features=2, model_path=str(model_path))

    assert loaded.model_available is True
    assert isinstance(loaded.model, GradientBoostingClassifier)


def test_load_model_rejects_incompatible_metadata_before_pickle_load(
    monkeypatch,
    tmp_path,
):
    model_path = tmp_path / "legacy_ot_model.pkl"
    model_path.write_bytes(b"not-a-pickle")
    (tmp_path / "legacy_ot_model.pkl.meta.json").write_text(
        json.dumps(
            {
                "model_type": "GradientBoostingClassifier",
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

    trainer = OnlineTrainer(model_path=str(model_path))

    assert trainer.model_available is False
    assert isinstance(trainer.model, GradientBoostingClassifier)


def test_load_model_rejects_inconsistent_version_warning(monkeypatch, tmp_path):
    model_path = tmp_path / "warning_ot_model.pkl"
    model_path.write_bytes(b"pickle-bytes")
    (tmp_path / "warning_ot_model.pkl.meta.json").write_text(
        json.dumps(
            {
                "model_type": "GradientBoostingClassifier",
                "sklearn_version": SKLEARN_VERSION,
            }
        ),
        encoding="utf-8",
    )

    def fake_load(_path):
        warnings.warn(
            InconsistentVersionWarning(
                estimator_name="GradientBoostingClassifier",
                current_sklearn_version=SKLEARN_VERSION,
                original_sklearn_version="1.8.0",
            )
        )
        return object()

    monkeypatch.setattr(joblib, "load", fake_load)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", InconsistentVersionWarning)
        trainer = OnlineTrainer(model_path=str(model_path))

    assert not [
        warning
        for warning in caught
        if isinstance(warning.message, InconsistentVersionWarning)
    ]
    assert trainer.model_available is False
    assert isinstance(trainer.model, GradientBoostingClassifier)
