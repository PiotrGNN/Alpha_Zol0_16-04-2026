import asyncio
import logging
from pathlib import Path
from core.MarketDataFetcher import MarketDataFetcher
from core.db_utils import save_decision_to_db, save_equity_to_db
from datetime import datetime, timezone
from utils.config_loader import load_config
import time
import os
from core.InfinityLayerLogger import InfinityLayerLogger


def _resolve_repo_config_path():
    return Path(__file__).resolve().parents[1] / "config" / "config.yaml"


class BotCoreAsync:
    def __init__(self, strategy_router, position_manager):
        self.router = strategy_router
        self.pm = position_manager
        self.running = True
        config = load_config(_resolve_repo_config_path())
        self.config = config
        self.fetcher = MarketDataFetcher(market_type=config.get("market_type"))
        self.symbols = config.get("symbols", [config.get("symbol", "BTC-USDT")])
        self.last_prices = {s: None for s in self.symbols}
        self._balance_cache = {"value": None, "ts": 0.0}
        self._last_exec_ts = {}
        self.infinity_logger = InfinityLayerLogger()
        try:
            self.ohlcv_limit = int(os.environ.get("OHLCV_LIMIT", "120"))
        except Exception:
            self.ohlcv_limit = 120
        try:
            self.execution_cooldown_sec = int(
                os.environ.get(
                    "EXECUTION_COOLDOWN_SEC",
                    os.environ.get("DECISION_THROTTLE_SEC", "0"),
                )
            )
        except Exception:
            self.execution_cooldown_sec = 0
        try:
            self.paper_alloc_pct = float(os.environ.get("PAPER_ALLOCATION_PCT", "0.01"))
        except Exception:
            self.paper_alloc_pct = 0.01
        if self.paper_alloc_pct <= 0:
            self.paper_alloc_pct = 0.01

    async def run_loop(self):
        last_equity_save = 0.0
        try:
            equity_interval_sec = int(os.environ.get("EQUITY_SNAPSHOT_SEC", "60"))
        except Exception:
            equity_interval_sec = 60
        while self.running:
            try:
                for symbol in self.symbols:
                    data = self.fetch_market_data(symbol)
                    decision = self.router.analyze(data)
                    now_ts = time.time()
                    price = (
                        data.get("price")
                        or data.get("last")
                        or data.get("close")
                        or data.get("markPrice")
                    )
                    balance = self._resolve_balance(symbol, data)
                    if decision.get("signal") in ["buy", "sell"]:
                        if (
                            self.execution_cooldown_sec > 0
                            and self._last_exec_ts.get(symbol) is not None
                            and (now_ts - self._last_exec_ts[symbol])
                            < self.execution_cooldown_sec
                        ):
                            logging.info(
                                (
                                    "Execution cooldown active for %s (%ss); "
                                    "skipping order."
                                ),
                                symbol,
                                self.execution_cooldown_sec,
                            )
                        else:
                            allocation_usdt = None
                            if balance is not None and price:
                                allocation_usdt = float(balance) * self.paper_alloc_pct
                            amount = (
                                allocation_usdt / float(price)
                                if allocation_usdt is not None
                                and price
                                and float(price) > 0
                                else 0.0
                            )
                            if amount > 0 and price is not None:
                                order = {
                                    "symbol": symbol,
                                    "side": decision["signal"],
                                    "amount": amount,
                                    "price": price,
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "strategy": decision.get("strategy") or "Universal",
                                }
                                was_open = self.pm.get_position(symbol) is not None
                                self.pm.update_position(symbol, order)
                                self._last_exec_ts[symbol] = now_ts
                                try:
                                    self.infinity_logger.log("order_simulated", order)
                                    if not was_open:
                                        self.infinity_logger.log(
                                            "position_open",
                                            {
                                                "symbol": symbol,
                                                "position": self.pm.get_position(
                                                    symbol
                                                ),
                                                "strategy": order.get("strategy"),
                                            },
                                        )
                                    self.infinity_logger.log(
                                        "position_update",
                                        {
                                            "symbol": symbol,
                                            "position": self.pm.get_position(symbol),
                                        },
                                    )
                                except Exception as exc:
                                    logging.warning(
                                        (
                                            "BotCoreAsync: runtime telemetry emit "
                                            "failed symbol=%s error=%s"
                                        ),
                                        symbol,
                                        exc,
                                    )
                    self.log_decision(symbol, decision, data)
                    if now_ts - last_equity_save >= equity_interval_sec:
                        pos = self.pm.get_position(symbol)
                        equity = (
                            balance
                            if balance is not None
                            else self._resolve_balance(symbol, data)
                        )
                        pnl = 0.0
                        if pos and price:
                            entry = pos.get("entry_price", price)
                            side = pos.get("side")
                            amount = pos.get("amount", 0)
                            if side == "buy":
                                pnl = (price - entry) * amount
                            elif side == "sell":
                                pnl = (entry - price) * amount
                            equity += pnl
                        save_equity_to_db(
                            timestamp=datetime.now(timezone.utc), equity=equity, pnl=pnl
                        )
                        last_equity_save = now_ts
            except Exception as e:
                logging.exception("Bot loop error: %s", str(e))
            await asyncio.sleep(5)

    def fetch_market_data(self, symbol):
        candles = self.fetcher.get_ohlcv(
            symbol,
            "1m",
            limit=self.ohlcv_limit,
        )
        if not candles:
            return {"price": None}
        last = candles[-1]
        self.last_prices[symbol] = last["close"]
        return {"price": last["close"], "ohlcv": candles}

    def log_decision(self, symbol, decision, data):
        logging.info(f"Decision: {symbol} {decision}")
        now = datetime.now(timezone.utc).isoformat()
        save_decision_to_db(
            timestamp=now,
            decision=decision.get("signal", "hold"),
            details=str(decision),
        )
        # Real PnL: equity = unrealized + realized (tu uproszczone)
        pos = self.pm.get_position(symbol)
        price = (
            data.get("price")
            or data.get("last")
            or data.get("close")
            or data.get("markPrice")
        )
        equity = self._resolve_balance(symbol, data)
        if equity is None:
            return
        pnl = 0.0
        if pos and price:
            entry = pos.get("entry_price", price)
            side = pos.get("side")
            amount = pos.get("amount", 0)
            if side == "buy":
                pnl = (price - entry) * amount
            elif side == "sell":
                pnl = (entry - price) * amount
            equity += pnl
        save_equity_to_db(timestamp=now, equity=equity, pnl=pnl)

    def _resolve_balance(self, symbol, data):
        try:
            balance_cache_sec = int(os.environ.get("BALANCE_CACHE_SEC", "10"))
        except Exception:
            balance_cache_sec = 10
        now_ts = time.time()
        if (
            balance_cache_sec > 0
            and self._balance_cache["value"] is not None
            and (now_ts - self._balance_cache["ts"]) < balance_cache_sec
        ):
            return self._balance_cache["value"]
        use_mock = os.environ.get("USE_MOCK", "0") == "1"
        config_balance = self.config.get("balance", 1000.0)
        if data and data.get("balance") is not None:
            try:
                self._balance_cache["value"] = float(data.get("balance"))
                self._balance_cache["ts"] = now_ts
                return self._balance_cache["value"]
            except Exception as exc:
                logging.warning(
                    "BotCoreAsync: invalid balance in data payload symbol=%s error=%s",
                    symbol,
                    exc,
                )
        if use_mock:
            self._balance_cache["value"] = config_balance
            self._balance_cache["ts"] = now_ts
            return config_balance
        try:
            from core.kucoin_futures_client import (
                KucoinFuturesClient,
                is_futures_symbol,
            )

            market_type = self.config.get("market_type") or os.environ.get(
                "MARKET_TYPE"
            )
            market_is_futures = (
                str(market_type).lower() == "futures"
                if market_type is not None
                else False
            ) or is_futures_symbol(symbol)
            if market_is_futures:
                overview = KucoinFuturesClient().get_account_overview(currency="USDT")
                for key in ("accountEquity", "marginBalance", "availableBalance"):
                    val = overview.get(key)
                    if val is not None:
                        self._balance_cache["value"] = float(val)
                        self._balance_cache["ts"] = now_ts
                        return self._balance_cache["value"]
        except Exception:
            if self._balance_cache["value"] is not None:
                return self._balance_cache["value"]
        # No mock and no real balance available -> do not fall back to config
        return self._balance_cache["value"]
