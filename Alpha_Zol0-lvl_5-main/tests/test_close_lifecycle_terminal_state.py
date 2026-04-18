from core.BotCore import _finalize_close_lifecycle_state


def test_finalize_close_lifecycle_state_records_success_snapshot():
    active_state = {
        "trade:abc": {
            "trade_id": "abc",
            "symbol": "BTCUSDTM",
            "close_requested_at": 1.0,
            "close_in_flight": True,
            "close_last_attempt_ts": 1.0,
            "close_attempt_count": 2,
            "last_selected_reason": "post_green_protective_exit",
            "last_block_code": None,
        }
    }
    terminal_state = {}

    snapshot = _finalize_close_lifecycle_state(
        active_state,
        terminal_state,
        "BTCUSDTM",
        {"trade_id": "abc"},
        success=True,
    )

    assert snapshot["close_finalized"] is True
    assert snapshot["close_finalization_status"] == "success"
    assert active_state == {}
    assert terminal_state["trade:abc"]["close_attempt_count"] == 2


def test_finalize_close_lifecycle_state_records_failure_snapshot():
    active_state = {
        "trade:xyz": {
            "trade_id": "xyz",
            "symbol": "ETHUSDTM",
            "close_requested_at": 2.0,
            "close_in_flight": True,
            "close_last_attempt_ts": 2.0,
            "close_attempt_count": 1,
            "last_selected_reason": "manual_close",
            "last_block_code": None,
        }
    }
    terminal_state = {}

    snapshot = _finalize_close_lifecycle_state(
        active_state,
        terminal_state,
        "ETHUSDTM",
        {"trade_id": "xyz"},
        success=False,
        block_code="POSITION_MANAGER_CLOSE_FAILED",
    )

    assert snapshot["close_finalized"] is False
    assert snapshot["close_finalization_status"] == "failed"
    assert snapshot["close_finalization_block_code"] == (
        "POSITION_MANAGER_CLOSE_FAILED"
    )
    assert active_state["trade:xyz"]["close_in_flight"] is False
    assert active_state["trade:xyz"]["last_block_code"] == (
        "POSITION_MANAGER_CLOSE_FAILED"
    )
    assert terminal_state["trade:xyz"]["close_attempt_count"] == 1


def test_finalize_close_lifecycle_state_handles_symbol_key_and_missing_context():
    active_state = {
        "symbol:BTCUSDTM": {
            "symbol": "BTCUSDTM",
            "close_requested_at": 3.0,
            "close_in_flight": True,
            "close_last_attempt_ts": 3.0,
            "close_attempt_count": 5,
            "last_selected_reason": "manual_close",
            "last_block_code": None,
        }
    }
    snapshot = _finalize_close_lifecycle_state(
        active_state,
        [],
        " BTCUSDTM ",
        {},
        success=False,
        block_code="POSITION_MANAGER_CLOSE_FAILED",
    )
    assert snapshot["close_finalized"] is False
    assert snapshot["close_finalization_status"] == "failed"
    assert snapshot["close_finalization_block_code"] == "POSITION_MANAGER_CLOSE_FAILED"
    assert snapshot["close_in_flight"] is False
    assert active_state["symbol:BTCUSDTM"]["close_in_flight"] is False
    assert active_state["symbol:BTCUSDTM"]["last_block_code"] == "POSITION_MANAGER_CLOSE_FAILED"
    assert active_state["symbol:BTCUSDTM"]["close_requested_at"] is None
    assert active_state["symbol:BTCUSDTM"]["close_last_attempt_ts"] == snapshot["close_finalized_at"]

    assert (
        _finalize_close_lifecycle_state(
            {},
            {},
            "   ",
            {},
            success=True,
        )
        is None
    )
    assert (
        _finalize_close_lifecycle_state(
            {"symbol:ETHUSDTM": None},
            {},
            "ETHUSDTM",
            {},
            success=True,
        )
        is None
    )
