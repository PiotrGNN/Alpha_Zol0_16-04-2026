from core.BotCore import run_bot, maybe_run_federated_learning
from core.InfinityLayerLogger import InfinityLayerLogger
from models.trend_predictor import TrendPredictor
from utils.news_social_scheduler import NewsSocialScheduler
from ai.OnlineTrainer import OnlineTrainer


def test_botcore_triggers_federated_update(monkeypatch):
    federated_updates = []
    fl_events = []

    def fake_federated_update(self, local_model, holdout=None, **kwargs):
        self.federated_global_model = local_model
        federated_updates.append(
            {
                "local_model": local_model,
                "holdout": list(holdout or []),
            }
        )
        return local_model

    def fake_log(self, event, details=None):
        if event == "fl_round":
            fl_events.append(details or {})

    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "1")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    monkeypatch.setenv("FL_ROUND_LIMIT", "1")
    monkeypatch.setenv("ZOL0_TOKEN", "test-token")
    monkeypatch.setattr(TrendPredictor, "federated_update", fake_federated_update)
    monkeypatch.setattr(InfinityLayerLogger, "log", fake_log)
    monkeypatch.setattr(NewsSocialScheduler, "start", lambda self: None)
    monkeypatch.setattr(
        OnlineTrainer,
        "fit_if_needed",
        lambda self, *args, **kwargs: None,
    )

    run_bot(simulate=True)

    assert federated_updates
    assert federated_updates[0]["local_model"] is not None
    assert federated_updates[0]["holdout"]
    assert fl_events
    assert fl_events[0]["symbol"]
    assert "global_model" in fl_events[0]


def test_botcore_maybe_run_federated_learning_integration():
    predictor = TrendPredictor()
    infinity_logger = InfinityLayerLogger()
    candles = [{"close": float(i)} for i in range(1, 21)]

    executed = maybe_run_federated_learning(
        federated_round=1,
        fl_round_limit=1,
        symbol="BTC-USDT",
        candles=candles,
        trend_predictor=predictor,
        infinity_logger=infinity_logger,
        logger=None,
    )

    assert executed is True
    assert predictor.federated_global_model is not None

    fl_round_logs = [entry for entry in infinity_logger.logs if entry["event"] == "fl_round"]
    assert len(fl_round_logs) == 1
    assert fl_round_logs[0]["details"]["symbol"] == "BTC-USDT"
    assert "global_model" in fl_round_logs[0]["details"]
