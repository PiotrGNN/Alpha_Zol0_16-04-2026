from core.BotCore import _default_entry_meanreversion_enable


def test_default_entry_meanreversion_enable_is_true_in_paper(monkeypatch):
    monkeypatch.setenv("LIVE", "0")
    assert _default_entry_meanreversion_enable() is True


def test_default_entry_meanreversion_enable_is_false_in_live(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    assert _default_entry_meanreversion_enable() is False
