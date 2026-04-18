# E2E PAPER loop offline (no network)
import time as _time

from core.BotCore import run_bot


def test_paper_loop_offline_no_network(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "1")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    monkeypatch.setenv("LIVE", "0")

    import requests

    def fail_net(*args, **kwargs):
        raise AssertionError("Network call blocked in PAPER offline test")

    monkeypatch.setattr(requests, "get", fail_net)
    monkeypatch.setattr(requests, "post", fail_net)

    import utils.news_social_scheduler as nss

    monkeypatch.setattr(nss.NewsSocialScheduler, "start", lambda self: None)

    import core.db_utils as dbu

    monkeypatch.setattr(
        dbu, "SessionLocal", lambda: (_ for _ in ()).throw(Exception("DB disabled"))
    )

    # Freeze time for deterministic mock candles
    monkeypatch.setattr(_time, "time", lambda: 1700000000)

    result = run_bot(simulate=True)
    assert result is None
