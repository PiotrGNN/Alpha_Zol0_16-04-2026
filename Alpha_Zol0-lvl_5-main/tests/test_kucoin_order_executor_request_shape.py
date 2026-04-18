# KuCoin OrderExecutor request shape (no real network)
from core.OrderExecutor import OrderExecutor
from core import kill_switch


def test_kucoin_order_executor_request_shape(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("LIVE_ARMED", "1")
    monkeypatch.setenv("LIVE_APPROVAL", "I_UNDERSTAND_LIVE_RISK")
    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    monkeypatch.setenv("KUCOIN_API_KEY", "k")
    monkeypatch.setenv("KUCOIN_API_SECRET", "s")
    monkeypatch.setenv("KUCOIN_API_PASSPHRASE", "p")
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
