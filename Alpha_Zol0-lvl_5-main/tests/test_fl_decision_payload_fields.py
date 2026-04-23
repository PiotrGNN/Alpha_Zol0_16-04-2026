from core.BotCore import _attach_fl_trend_payload_fields


def test_attach_fl_trend_payload_fields_emits_all_contract_keys():
    payload = {"symbol": "BTC-USDT", "trend": "UP"}
    hint = {
        "available": True,
        "applied": True,
        "direction": "UP",
        "threshold": 0.01,
        "relative_diff": 0.025,
        "base_pred": 0,
        "final_pred": 1,
    }
    counts = {"BTC-USDT": 3}

    out = _attach_fl_trend_payload_fields(
        payload,
        fl_trend_hint=hint,
        fl_trend_override_counts=counts,
        symbol="BTC-USDT",
    )

    assert out is payload
    assert out["fl_trend_hint"] == hint
    assert out["fl_base_pred"] == 0
    assert out["fl_trend_override_applied"] is True
    assert out["fl_trend_override_direction"] == "UP"
    assert out["fl_trend_override_count_symbol"] == 3


def test_attach_fl_trend_payload_fields_serializes_base_pred_for_neutral_up_and_down():
    for base_pred in (-1, 0, 1):
        payload = {"symbol": "BTC-USDT", "trend": "SIDE"}
        hint = {
            "available": True,
            "applied": base_pred == 0,
            "direction": "UP" if base_pred == 0 else None,
            "base_pred": base_pred,
            "final_pred": 1 if base_pred == 0 else base_pred,
        }

        out = _attach_fl_trend_payload_fields(
            payload,
            fl_trend_hint=hint,
            fl_trend_override_counts={"BTC-USDT": 1},
            symbol="BTC-USDT",
        )

        assert out["fl_base_pred"] == base_pred


def test_attach_fl_trend_payload_fields_handles_missing_hint_and_counts():
    payload = {"symbol": "ETH-USDT", "trend": "SIDE"}

    out = _attach_fl_trend_payload_fields(
        payload,
        fl_trend_hint=None,
        fl_trend_override_counts={},
        symbol="ETH-USDT",
    )

    assert out["fl_trend_hint"] is None
    assert out["fl_base_pred"] is None
    assert out["fl_trend_override_applied"] is False
    assert out["fl_trend_override_direction"] is None
    assert out["fl_trend_override_count_symbol"] == 0
