import sys
import threading
import asyncio
import runpy

import pytest

import main


def test_main_initializes_db_and_exits_cleanly_on_keyboard_interrupt(monkeypatch):
    calls = {"init_db": 0, "run_bot": 0}

    def fake_init_db():
        calls["init_db"] += 1

    def fake_run_bot(simulate=False):
        calls["run_bot"] += 1
        raise KeyboardInterrupt()

    monkeypatch.setattr(main, "init_db", fake_init_db)
    monkeypatch.setattr(main, "run_bot", fake_run_bot)
    monkeypatch.setattr(sys, "argv", ["main.py", "--mode", "simulate", "--no-api"])

    with pytest.raises(SystemExit) as excinfo:
        main.main()

    assert excinfo.value.code == 0
    assert calls["init_db"] == 1
    assert calls["run_bot"] == 1


def test_main_exits_when_db_initialization_fails(monkeypatch):
    calls = {"init_db": 0}

    def fake_init_db():
        calls["init_db"] += 1
        raise RuntimeError("db boom")

    monkeypatch.setattr(main, "init_db", fake_init_db)
    monkeypatch.setattr(sys, "argv", ["main.py", "--mode", "simulate", "--no-api"])

    with pytest.raises(SystemExit) as excinfo:
        main.main()

    assert excinfo.value.code == 1
    assert calls["init_db"] == 1


def test_main_starts_background_threads_when_api_enabled(monkeypatch):
    calls = {"init_db": 0, "run_bot": 0, "api_thread_started": 0, "monitor_started": 0}

    def fake_init_db():
        calls["init_db"] += 1

    def fake_run_bot(simulate=False):
        calls["run_bot"] += 1
        raise KeyboardInterrupt()

    class DummyThread:
        def __init__(self, target=None, daemon=None):
            self.target = target
            self.daemon = daemon

        def start(self):
            if self.target is main.start_api:
                calls["api_thread_started"] += 1
            if self.target is main.start_system_monitor:
                calls["monitor_started"] += 1

    monkeypatch.setattr(main, "init_db", fake_init_db)
    monkeypatch.setattr(main, "run_bot", fake_run_bot)
    monkeypatch.setattr(threading, "Thread", DummyThread)
    monkeypatch.setattr(sys, "argv", ["main.py", "--mode", "simulate"])

    with pytest.raises(SystemExit):
        main.main()

    assert calls["init_db"] == 1
    assert calls["run_bot"] == 1
    assert calls["api_thread_started"] == 1
    assert calls["monitor_started"] == 1


def test_start_api_logs_failure(monkeypatch):
    errors = []

    def fake_run(*args, **kwargs):
        raise RuntimeError("api boom")

    def fake_error(msg):
        errors.append(msg)

    monkeypatch.setattr(main.uvicorn, "run", fake_run)
    monkeypatch.setattr(main.logger, "error", fake_error)

    main.start_api()

    assert errors
    assert "Failed to start FastAPI server" in errors[0]


def test_start_system_monitor_logs_failure(monkeypatch):
    errors = []

    class DummyLoop:
        def create_task(self, coro):
            try:
                coro.close()
            except Exception:
                pass
            return coro

        def run_forever(self):
            raise RuntimeError("monitor boom")

    def fake_new_loop():
        return DummyLoop()

    def fake_set_event_loop(loop):
        return None

    def fake_error(msg):
        errors.append(msg)

    monkeypatch.setattr(asyncio, "new_event_loop", fake_new_loop)
    monkeypatch.setattr(asyncio, "set_event_loop", fake_set_event_loop)
    monkeypatch.setattr(main.logger, "error", fake_error)

    main.start_system_monitor()

    assert errors
    assert "Failed to start system monitor" in errors[0]


def test_main_logs_restart_on_generic_exception(monkeypatch):
    calls = {"init_db": 0, "run_bot": 0, "sleep": 0, "error": []}

    def fake_init_db():
        calls["init_db"] += 1

    def fake_run_bot(simulate=False):
        calls["run_bot"] += 1
        if calls["run_bot"] == 1:
            raise RuntimeError("boom")
        raise KeyboardInterrupt()

    def fake_sleep(seconds):
        calls["sleep"] += 1
        return None

    def fake_error(msg, exc_info=False):
        calls["error"].append(msg)

    monkeypatch.setattr(main, "init_db", fake_init_db)
    monkeypatch.setattr(main, "run_bot", fake_run_bot)
    monkeypatch.setattr(main.time, "sleep", fake_sleep)
    monkeypatch.setattr(main.logger, "error", fake_error)
    monkeypatch.setattr(sys, "argv", ["main.py", "--mode", "simulate", "--no-api", "--autorestart", "1"])

    with pytest.raises(SystemExit):
        main.main()

    assert calls["init_db"] == 1
    assert calls["run_bot"] >= 1
    assert calls["sleep"] == 1
    assert any("Bot crashed" in msg for msg in calls["error"])


def test_module_entrypoint_guard_invokes_main(monkeypatch):
    calls = {"init_db": 0, "run_bot": 0}

    def fake_init_db():
        calls["init_db"] += 1

    def fake_run_bot(simulate=False):
        calls["run_bot"] += 1
        raise KeyboardInterrupt()

    monkeypatch.setattr(sys.modules["core.db_models"], "init_db", fake_init_db)
    monkeypatch.setattr(sys.modules["core.BotCore"], "run_bot", fake_run_bot)
    monkeypatch.setattr(sys, "argv", ["main.py", "--mode", "simulate", "--no-api"])

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("main", run_name="__main__")

    assert excinfo.value.code == 0
    assert calls["init_db"] == 1
    assert calls["run_bot"] == 1
