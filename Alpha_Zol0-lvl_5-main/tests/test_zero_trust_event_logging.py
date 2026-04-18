# Reject paths must emit security events
from core.OrderExecutor import OrderExecutor


def test_log_event_on_block_invalid_payload(monkeypatch):
    import security.zero_trust as zt

    events = []

    def fake_log_event(message):
        events.append(message)

    monkeypatch.setattr(zt, "log_event", fake_log_event)
    executor = OrderExecutor()

    res = executor.execute_order(None, use_rest=True)

    assert res == {"error": "invalid_payload"}
    assert events == ["ORDER_BLOCKED:INVALID_PAYLOAD"]


def test_log_event_on_block_invalid_side(monkeypatch):
    import security.zero_trust as zt

    events = []

    def fake_log_event(message):
        events.append(message)

    monkeypatch.setattr(zt, "log_event", fake_log_event)
    executor = OrderExecutor()

    res = executor.execute_order(
        {
            "symbol": "BTCUSDT",
            "side": "HOLD",
            "amount": 1,
            "price": 10000,
        },
        use_rest=True,
    )

    assert res == {"error": "invalid_side"}
    assert events == ["ORDER_BLOCKED:INVALID_SIDE"]


def test_log_event_on_block_unauthorized(monkeypatch):
    import security.zero_trust as zt

    events = []

    def fake_log_event(message):
        events.append(message)

    monkeypatch.setattr(zt, "log_event", fake_log_event)
    monkeypatch.delenv("ZOL0_TOKEN", raising=False)
    executor = OrderExecutor()

    res = executor.execute_order(
        {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "amount": 1,
            "price": 10000,
        },
        use_rest=True,
    )

    assert res == {"error": "unauthorized"}
    assert events == ["ORDER_BLOCKED:UNAUTHORIZED"]
