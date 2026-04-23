import logging
import csv
import io
from pathlib import Path


def test_no_csv_in_live_mode(monkeypatch, caplog):
    monkeypatch.setenv("LIVE", "1")
    caplog.set_level(logging.INFO)

    test_dir = Path("tmp") / "test_logging_storage_policy"
    test_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(test_dir)

    autopsy_dir = Path("autopsy")
    autopsy_dir.mkdir(parents=True, exist_ok=True)

    class DummyStrategy:
        def __init__(self, name):
            self.name = name

    from strategies.DynamicStrategyRouter import DynamicStrategyRouter

    router = DynamicStrategyRouter(strategies=[DummyStrategy("A"), DummyStrategy("B")])
    router.switch_strategy("B")

    from core.MetaStrategyRouter import MetaStrategyRouter

    mrouter = MetaStrategyRouter(
        strategies=[DummyStrategy("A"), DummyStrategy("B")],
        use_llm=False,
    )
    mrouter.log_switch("A", "B")

    log_path = autopsy_dir / "decision_log.csv"
    assert not log_path.exists()
    assert any("CSV logging disabled" in r.getMessage() for r in caplog.records)


def test_append_decision_log_csv_row_escapes_comma_payload():
    from core.BotCore import append_decision_log_csv_row

    buf = io.StringIO()
    details = '{"strategy":"trend,fast","edge":0.0012}'
    append_decision_log_csv_row(
        buf,
        "2026-04-17T12:00:00+00:00",
        "buy",
        details,
    )
    rows = list(csv.reader(io.StringIO(buf.getvalue())))
    assert rows == [["2026-04-17T12:00:00+00:00", "buy", details]]


def test_append_decision_log_csv_row_without_details_keeps_two_columns():
    from core.BotCore import append_decision_log_csv_row

    buf = io.StringIO()
    append_decision_log_csv_row(
        buf,
        "2026-04-17T12:00:00+00:00",
        "hold",
        None,
    )
    rows = list(csv.reader(io.StringIO(buf.getvalue())))
    assert rows == [["2026-04-17T12:00:00+00:00", "hold"]]


def test_apply_ai_vote_is_telemetry_only():
    from core.BotCore import apply_ai_vote

    signal_score, signal_votes, ai_vote = apply_ai_vote(
        0.75,
        [],
        1,
        0.2,
    )

    assert signal_score == 0.75
    assert ai_vote == "buy"
    assert signal_votes == [
        {
            "strategy": "OnlineTrainer",
            "side": "buy",
            "allocation": 0.2,
        }
    ]
