from core.BotCore import _default_side_guard_enable


def test_default_side_guard_enabled_in_paper(monkeypatch):
    monkeypatch.setenv("LIVE", "0")
    assert _default_side_guard_enable() is True


def test_default_side_guard_disabled_in_live(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    assert _default_side_guard_enable() is False
