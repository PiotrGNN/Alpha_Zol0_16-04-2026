# KuCoin OrderExecutor request shape (no real network)
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


def test_kucoin_order_executor_request_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("LIVE_ARMED", "1")
    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    monkeypatch.setenv("KUCOIN_API_KEY", "k")
    monkeypatch.setenv("KUCOIN_API_SECRET", "s")
    monkeypatch.setenv("KUCOIN_API_PASSPHRASE", "p")
    _write_ready_snapshot(monkeypatch, tmp_path)
    kill_switch.reset()

    captured = {}

    def mock_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return {"code": "200000", "data": {"orderId": "abc"}}

    executor = OrderExecutor()
    executor._requests_post = mock_post
    order = {
        "symbol": "BTC-USDT",
        "side": "BUY",
        "amount": 1,
        "price": 10000,
        "sl": 0.5,
        "tp": 1.0,
    }
    res = executor.execute_order(order, use_rest=True)

    assert isinstance(res, dict) and res.get("code") == "200000"
    assert "kucoin.com" in captured["url"]
    payload = captured["json"]
    assert payload is not None
    for key in ("symbol", "side", "price", "size", "type"):
        assert key in payload
    for forbidden in ("qty", "sl", "tp"):
        assert forbidden not in payload
