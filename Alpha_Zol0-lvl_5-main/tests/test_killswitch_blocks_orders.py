# Kill-switch must block order execution
from core.OrderExecutor import OrderExecutor
from core import kill_switch


def test_killswitch_blocks_order_executor(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    kill_switch.reset()
    kill_switch.trigger("test")

    executor = OrderExecutor()
    order = {
        "symbol": "BTC-USDT",
        "side": "BUY",
        "amount": 1,
        "price": 10000,
        "sl": 0.5,
        "tp": 1.0,
    }

    def fail_post(*args, **kwargs):
        raise AssertionError("Network should not be called")

    executor._requests_post = fail_post
    res = executor.execute_order(order, use_rest=True)
    assert isinstance(res, dict) and res.get("error") == "killswitch"
