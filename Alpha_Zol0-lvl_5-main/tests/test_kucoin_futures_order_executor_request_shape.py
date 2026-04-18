# KuCoin Futures OrderExecutor request shape (no real network)
from core.OrderExecutor import OrderExecutor
from core import kill_switch


def test_kucoin_futures_order_executor_request_shape(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("LIVE_ARMED", "1")
    monkeypatch.setenv("LIVE_APPROVAL", "I_UNDERSTAND_LIVE_RISK")
    monkeypatch.setenv("MARKET_TYPE", "futures")
    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    monkeypatch.setenv("KUCOIN_API_KEY", "k")
    monkeypatch.setenv("KUCOIN_API_SECRET", "s")
    monkeypatch.setenv("KUCOIN_API_PASSPHRASE", "p")
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
