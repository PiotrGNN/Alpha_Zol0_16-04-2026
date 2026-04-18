# Test that OrderExecutor enforces Zero-Trust for REST calls
from core.OrderExecutor import OrderExecutor
from core import kill_switch


def test_order_blocked_without_token(monkeypatch):
    executor = OrderExecutor()
    order = {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "amount": 1,
        "price": 10000,
        "sl": 0.5,
        "tp": 1.0,
    }
    # Ensure no token in env
    monkeypatch.delenv("ZOL0_TOKEN", raising=False)
    res = executor.execute_order(order, use_rest=True)
    assert isinstance(res, dict) and res.get("error") == "unauthorized"


def test_order_allowed_with_token(monkeypatch):
    kill_switch.reset()
    executor = OrderExecutor()
    order = {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "amount": 1,
        "price": 10000,
        "sl": 0.5,
        "tp": 1.0,
    }
    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("LIVE_ARMED", "1")
    monkeypatch.setenv("LIVE_APPROVAL", "I_UNDERSTAND_LIVE_RISK")
    monkeypatch.setenv("KUCOIN_API_KEY", "k")
    monkeypatch.setenv("KUCOIN_API_SECRET", "s")
    monkeypatch.setenv("KUCOIN_API_PASSPHRASE", "p")

    # Mock rest post to return success
    def mock_post(*args, **kwargs):
        return {"retCode": 0, "retMsg": "OK"}

    executor._requests_post = mock_post
    res = executor.execute_order(order, use_rest=True)
    assert isinstance(res, dict) and (
        res.get("retCode") == 0 or res.get("retMsg") == "OK"
    )
