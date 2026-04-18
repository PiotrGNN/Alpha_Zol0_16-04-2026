import importlib
import time as _time
import warnings

from urllib3.exceptions import SystemTimeWarning

warnings.filterwarnings("ignore", category=SystemTimeWarning)

botcore = importlib.import_module("core.BotCore")


def test_botcore_balance_cache(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "0")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("MARKET_TYPE", "futures")
    monkeypatch.setenv("BALANCE_CACHE_SEC", "10")
    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")

    calls = {"overview": 0}

    def fake_get_account_overview(self, currency="USDT"):
        calls["overview"] += 1
        return {"accountEquity": "123.0"}

    def fake_config(_path):
        return {
            "api_key": None,
            "api_secret": None,
            "balance": 10000.0,
            "retrain_interval": 10000000,
            "sl_pct": 0.5,
            "tp_pct": 1.0,
            "symbols": ["BTCUSDTM", "ETHUSDTM"],
            "symbol": "BTCUSDTM",
            "timeframe": 1,
            "market_type": "futures",
        }

    def fake_get_ohlcv(self, symbol, interval, limit=10):
        return [
            {"timestamp": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"timestamp": 2, "open": 2, "high": 2, "low": 2, "close": 2, "volume": 1},
            {"timestamp": 3, "open": 3, "high": 3, "low": 3, "close": 3, "volume": 1},
        ]

    def fake_apply_risk(
        self,
        signal,
        price,
        balance,
        position_status,
        pnl_history,
        symbol,
        global_pnl_history=None,
        open_positions=None,
    ):
        return False, None, None, 0.0

    class DummyQuery:
        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def all(self):
            return []

    class DummySession:
        def query(self, *args, **kwargs):
            return DummyQuery()

        def close(self):
            return None

    import utils.news_social_scheduler as nss
    import core.db_models as db_models
    import core.MarketDataFetcher as mdf
    import core.RiskManager as risk_mgr
    import core.DynamicStrategyRouter as dsr
    import core.kucoin_futures_client as kfc

    monkeypatch.setattr(nss.NewsSocialScheduler, "start", lambda self: None)
    monkeypatch.setattr(db_models, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(mdf.MarketDataFetcher, "get_ohlcv", fake_get_ohlcv)
    monkeypatch.setattr(risk_mgr.RiskManager, "apply_risk", fake_apply_risk)
    monkeypatch.setattr(dsr.DynamicStrategyRouter, "route", lambda self, state: [])
    monkeypatch.setattr(
        kfc.KucoinFuturesClient, "get_account_overview", fake_get_account_overview
    )
    monkeypatch.setattr(botcore, "load_config", fake_config)
    monkeypatch.setattr(botcore, "save_decision_to_db", lambda *a, **k: None)
    monkeypatch.setattr(botcore, "save_equity_to_db", lambda *a, **k: None)

    monkeypatch.setattr(_time, "time", lambda: 1000.0)

    botcore.run_bot(simulate=True)
    assert calls["overview"] == 1
