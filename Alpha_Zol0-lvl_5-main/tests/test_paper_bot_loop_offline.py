# Test BotCore runs one cycle in PAPER offline mode
from core.BotCore import run_bot


def test_paper_bot_loop_offline(monkeypatch):
    # Enable mock data and one-cycle run
    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "1")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    # Run bot in simulate mode (no REST calls)
    result = run_bot(simulate=True)
    # If it returns, it processed one cycle without network/DB crashing
    assert result is None
