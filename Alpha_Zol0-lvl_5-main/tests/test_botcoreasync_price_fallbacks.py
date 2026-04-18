import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import core.BotCoreAsync as botcore_async
from core.BotCoreAsync import BotCoreAsync
from core.PositionManager import PositionManager


class DummyRouter:
    def analyze(self, data):
        return {"signal": "hold"}


def test_botcoreasync_price_fallbacks(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "1")
    captured = []

    def fake_save_equity_to_db(timestamp, equity, pnl):
        captured.append((equity, pnl))
        return True

    def fake_save_decision_to_db(*args, **kwargs):
        return True

    monkeypatch.setattr(botcore_async, "save_equity_to_db", fake_save_equity_to_db)
    monkeypatch.setattr(botcore_async, "save_decision_to_db", fake_save_decision_to_db)

    pm = PositionManager()
    pm.open_position(
        {
            "symbol": "BTCUSDTM",
            "side": "buy",
            "entry_price": 100.0,
            "amount": 1,
            "timestamp": "t",
        }
    )

    bot = BotCoreAsync(DummyRouter(), pm)
    base_balance = bot.config.get("balance", 1000.0)
    for key in ["price", "last", "close", "markPrice"]:
        captured.clear()
        bot.log_decision("BTCUSDTM", {"signal": "hold"}, {key: 110.0})
        assert captured, f"no equity snapshot for key={key}"
        equity, pnl = captured[-1]
        assert pnl == 10.0
        assert equity == base_balance + 10.0


def test_botcoreasync_balance_cache(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "0")
    monkeypatch.setenv("MARKET_TYPE", "futures")
    monkeypatch.setenv("BALANCE_CACHE_SEC", "10")

    calls = {"overview": 0}

    def fake_get_account_overview(self, currency="USDT"):
        calls["overview"] += 1
        return {"accountEquity": "200.0"}

    import core.kucoin_futures_client as kfc

    monkeypatch.setattr(
        kfc.KucoinFuturesClient, "get_account_overview", fake_get_account_overview
    )
    monkeypatch.setattr(botcore_async.time, "time", lambda: 1000.0)

    bot = BotCoreAsync(DummyRouter(), PositionManager())
    b1 = bot._resolve_balance("BTCUSDTM", {})
    b2 = bot._resolve_balance("BTCUSDTM", {})
    assert b1 == 200.0
    assert b2 == 200.0
    assert calls["overview"] == 1


def test_botcoreasync_config_path_is_independent_of_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("USE_MOCK", "1")

    bot = BotCoreAsync(DummyRouter(), PositionManager())

    assert bot.config["market_type"] == "futures"
    assert bot.config["symbol"] == "ETHUSDTM"
