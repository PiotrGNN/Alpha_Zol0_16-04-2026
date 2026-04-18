# test_order_executor.py – Testy jednostkowe OrderExecutor
# (REST, retry, throttle)
from core.OrderExecutor import OrderExecutor


def test_execute_order_rest_retry_throttle(caplog, monkeypatch):
    caplog.set_level("INFO")
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("LIVE_ARMED", "1")
    monkeypatch.setenv("LIVE_APPROVAL", "I_UNDERSTAND_LIVE_RISK")
    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    monkeypatch.setenv("KUCOIN_API_KEY", "k")
    monkeypatch.setenv("KUCOIN_API_SECRET", "s")
    monkeypatch.setenv("KUCOIN_API_PASSPHRASE", "p")
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
