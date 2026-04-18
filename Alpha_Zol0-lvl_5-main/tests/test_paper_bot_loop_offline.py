# Test BotCore runs one cycle in PAPER offline mode
import core.BotCore as botcore

from core.BotCore import run_bot


class _RecordingPlatformManager:
    instances = []

    def __init__(self, mode="live-paper"):
        self.mode = mode
        self.register_calls = []
        self.start_calls = []
        self.stop_calls = []
        self.__class__.instances.append(self)

    def register_platform(self, name, api=None, websocket=None):
        self.register_calls.append(
            {"name": name, "api": api, "websocket": websocket}
        )

    def start_platform_stream(self, name, symbols, market_type=None):
        self.start_calls.append(
            {
                "name": name,
                "symbols": list(symbols or []),
                "market_type": market_type,
            }
        )
        return {"status": "connecting"}

    def stop_platform_stream(self, name):
        self.stop_calls.append(name)


def test_paper_bot_loop_offline(monkeypatch):
    # Enable mock data and one-cycle run
    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "1")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    # Run bot in simulate mode (no REST calls)
    result = run_bot(simulate=True)
    # If it returns, it processed one cycle without network/DB crashing
    assert result is None


def test_paper_bot_loop_autostarts_platform_stream_with_feature_flag(monkeypatch):
    _RecordingPlatformManager.instances.clear()
    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "1")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    monkeypatch.setenv("ZOL0_PLATFORM_STREAM_AUTO_START", "1")

    import platforms.MetaPlatformManager as meta_platform_module

    monkeypatch.setattr(
        meta_platform_module,
        "MetaPlatformManager",
        _RecordingPlatformManager,
    )

    result = botcore.run_bot(simulate=True)

    assert result is None
    assert len(_RecordingPlatformManager.instances) == 1
    manager = _RecordingPlatformManager.instances[0]
    assert manager.mode == "live-paper"
    assert manager.register_calls[0]["name"] == "kucoin"
    assert manager.start_calls[0]["name"] == "kucoin"
    assert manager.start_calls[0]["symbols"]
    assert manager.stop_calls == ["kucoin"]
