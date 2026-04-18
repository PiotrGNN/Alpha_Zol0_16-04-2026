"""
P3-6  BotCoreAsync.run_loop() exits cleanly when running=False.
"""
import asyncio
from unittest.mock import MagicMock, patch


def _make_bot(monkeypatch):
    """Construct a BotCoreAsync with all I/O patched out."""
    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("OHLCV_LIMIT", "10")

    config = {
        "symbols": ["BTCUSDTM"],
        "market_type": "futures",
        "balance": 1000.0,
    }

    import utils.config_loader as cl
    monkeypatch.setattr(cl, "load_config", lambda p: config)

    # Patch MarketDataFetcher at construction time
    mock_fetcher = MagicMock()
    mock_fetcher.get_ohlcv.return_value = []
    monkeypatch.setattr(
        "core.BotCoreAsync.MarketDataFetcher", lambda **kwargs: mock_fetcher
    )

    # Patch InfinityLayerLogger at construction time
    mock_logger = MagicMock()
    monkeypatch.setattr(
        "core.BotCoreAsync.InfinityLayerLogger", lambda: mock_logger
    )

    import core.db_utils as dbu
    monkeypatch.setattr(dbu, "save_decision_to_db", lambda *a, **k: True)
    monkeypatch.setattr(dbu, "save_equity_to_db", lambda *a, **k: True)
    monkeypatch.setattr(
        "core.BotCoreAsync.save_equity_to_db", lambda *a, **k: True
    )

    mock_router = MagicMock()
    mock_router.analyze.return_value = {"signal": "hold"}
    mock_pm = MagicMock()
    mock_pm.get_position.return_value = None

    from core.BotCoreAsync import BotCoreAsync
    bot = BotCoreAsync(mock_router, mock_pm)
    return bot


def test_run_loop_exits_immediately_when_running_false(monkeypatch):
    """
    When running=False before run_loop() is called, the while loop must
    exit immediately without blocking or raising any exception.
    """
    bot = _make_bot(monkeypatch)
    bot.running = False
    asyncio.run(bot.run_loop())  # must return without hanging


def test_run_loop_exits_after_one_iteration_when_running_toggled(monkeypatch):
    """
    When running is set to False inside the loop (via side_effect on analyze),
    run_loop must finish the current iteration and then exit cleanly.
    """
    bot = _make_bot(monkeypatch)

    call_count = [0]

    def stop_after_one(data):
        call_count[0] += 1
        bot.running = False  # stop after first iteration
        return {"signal": "hold"}

    bot.router.analyze.side_effect = stop_after_one

    # Patch fetch_market_data to return minimal dict (avoids fetcher.get_ohlcv)
    bot.fetch_market_data = lambda sym: {"symbol": sym, "price": 90000.0}

    # Patch asyncio.sleep to avoid 5-second wait at end of each iteration
    async def instant_sleep(s):
        pass

    with patch("asyncio.sleep", instant_sleep):
        asyncio.run(bot.run_loop())

    assert call_count[0] == 1, (
        f"Expected exactly 1 analysis call before exit, got {call_count[0]}"
    )
