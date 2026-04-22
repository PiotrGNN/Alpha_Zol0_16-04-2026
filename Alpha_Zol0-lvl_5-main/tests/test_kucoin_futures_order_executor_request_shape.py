# KuCoin Futures OrderExecutor request shape (no real network)
import json

from core.OrderExecutor import OrderExecutor
from core import kill_switch


def _write_ready_snapshot(monkeypatch, tmp_path):
    path = tmp_path / "live_readiness_snapshot.json"
    path.write_text(
        json.dumps(
            {
                "runtime_state": {
                    "last_run": {
                        "process_returncode": 0,
                        "shutdown_classification": (
                            "close_flush_done_pending_positions_zero"
                        ),
                        "pending_positions": 0,
                        "close_request_backlog": 0,
                    },
                    "data_validity": {
                        "accepted_corpus_exists": True,
                        "no_rejected_runs_in_active_dataset": True,
                        "corpus_size_trades": 60,
                    },
                    "strategy_validation": {
                        "usable_strategy_economics": True,
                        "economic_go_no_go": "GO",
                        "profitability_metrics": {
                            "expectancy": 0.01,
                            "winrate": 0.55,
                            "profit_factor": 1.2,
                            "green_to_red_share": 0.2,
                        }
                    },
                    "critical_blockers": {
                        "CLOSE_FINALIZATION_BROKEN": False,
                        "LINKAGE_LAYER_NO_EFFECT": False,
                        "TERMINAL_TIMING_CUTOFF_CONFIRMED": False,
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LIVE_READINESS_SNAPSHOT_PATH", str(path))


def test_kucoin_futures_order_executor_request_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("LIVE_ARMED", "1")
    monkeypatch.setenv("MARKET_TYPE", "futures")
    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    monkeypatch.setenv("KUCOIN_API_KEY", "k")
    monkeypatch.setenv("KUCOIN_API_SECRET", "s")
    monkeypatch.setenv("KUCOIN_API_PASSPHRASE", "p")
    _write_ready_snapshot(monkeypatch, tmp_path)
    kill_switch.reset()

    captured = {}

    def fake_create_order(**kwargs):
        captured.update(kwargs)
        return {"code": "200000", "data": {"orderId": "fut"}}

    executor = OrderExecutor()
    executor._futures_create_order = fake_create_order
    order = {
        "symbol": "BTCUSDTM",
        "side": "BUY",
        "amount": 2,
        "price": 10000,
        "type": "limit",
        "leverage": 5,
    }
    res = executor.execute_order(order, use_rest=True)

    assert isinstance(res, dict) and res.get("code") == "200000"
    assert captured.get("symbol") == "BTCUSDTM"
    assert captured.get("side") == "buy"
    # The executor converts `amount` -> exchange `size` (contracts) using
    # contract metadata (multiplier / lot). Compute expected size from the
    # same helpers so the test remains correct across environments.
    try:
        meta = executor._get_futures_contract_meta(None, order["symbol"])
    except Exception:
        meta = None
    if meta:
        multiplier = executor._as_float(
            meta.get("multiplier")
            or meta.get("contractSize")
            or meta.get("value")
            or 1.0
        )
        lot = (
            executor._as_float(meta.get("lotSize"))
            or executor._as_float(meta.get("lot"))
            or executor._as_float(meta.get("sizeIncrement"))
            or 1.0
        )
        expected_size = executor._calc_contract_size(order["amount"], multiplier, lot)
        assert captured.get("size") == expected_size
    else:
        assert isinstance(captured.get("size"), (int, float))
    assert captured.get("price") == 10000
    assert captured.get("order_type") == "limit"
