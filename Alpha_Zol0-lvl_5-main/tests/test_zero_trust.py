# test_zero_trust.py – Testy jednostkowe dla security/zero_trust.py
from pathlib import Path

from security.zero_trust import authorize, log_event, validate_input


def test_validate_input():
    assert validate_input({}) is False
    assert validate_input(None) is False
    assert validate_input("not-a-dict") is False
    assert validate_input({"symbol": "BTCUSDTM"}) is True


def test_authorize_env(monkeypatch):
    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    assert authorize("testtoken") is True
    assert authorize("wrongtoken") is False


def test_authorize_rejects_missing_expected_or_candidate(monkeypatch):
    monkeypatch.delenv("ZOL0_TOKEN", raising=False)
    assert authorize("testtoken") is False
    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    assert authorize("") is False


def test_authorize_trims_token_whitespace(monkeypatch):
    monkeypatch.setenv("ZOL0_TOKEN", "  testtoken  \n")
    assert authorize("testtoken") is True
    assert authorize("  testtoken  ") is True


def test_log_event_writes_file_and_prints(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    log_event("test_event")
    captured = capsys.readouterr()
    assert "SECURITY EVENT: test_event" in captured.out
    log_path = Path("logs") / "security.log"
    assert log_path.exists()
    assert "SECURITY EVENT: test_event" in log_path.read_text(encoding="utf-8")


def test_log_event_falls_back_when_logging_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    def fake_mkdir(*args, **kwargs):
        raise PermissionError("blocked")

    monkeypatch.setattr("pathlib.Path.mkdir", fake_mkdir)

    log_event("test_event")
    captured = capsys.readouterr()
    assert "SECURITY EVENT (FAILED LOGGING): test_event" in captured.out
