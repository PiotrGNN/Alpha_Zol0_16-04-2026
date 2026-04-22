# test_order_executor.py – Testy jednostkowe OrderExecutor
# (REST, retry, throttle)
import json

from core.OrderExecutor import OrderExecutor


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


def test_execute_order_rest_retry_throttle(caplog, monkeypatch, tmp_path):
    caplog.set_level("INFO")
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("LIVE_ARMED", "1")
    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    monkeypatch.setenv("KUCOIN_API_KEY", "k")
    monkeypatch.setenv("KUCOIN_API_SECRET", "s")
    monkeypatch.setenv("KUCOIN_API_PASSPHRASE", "p")
    _write_ready_snapshot(monkeypatch, tmp_path)
    executor = OrderExecutor()
    order = {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "amount": 1,
        "price": 10000,
        "sl": 0.5,
        "tp": 1.0,
    }
    # Mock: first call raises, second returns dict
    call_state = {"n": 0}

    def mock_post(*args, **kwargs):
        if call_state["n"] == 0:
            call_state["n"] += 1
            raise Exception("Simulated REST failure for test")
        return {"retCode": 0, "retMsg": "OK"}

    executor._requests_post = mock_post
    executor.execute_order(
        order,
        use_rest=True,
        max_retries=3,
        throttle_sec=0.1,
    )
    rest_attempts = [r for r in caplog.records if "REST API attempt" in r.getMessage()]
    success = any("REST API success" in r.getMessage() for r in caplog.records)
    assert len(rest_attempts) == 2, "Sukces na 2 próbie"
    assert success, "Expected success but got failure"
