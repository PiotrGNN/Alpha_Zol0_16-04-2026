import logging

from core.PositionManager import PositionManager


def test_sync_map_from_list_skips_malformed_entries_and_keeps_last_duplicate(
    caplog,
):
    caplog.set_level(logging.WARNING)

    manager = PositionManager()
    manager.positions = [
        {"symbol": "BTCUSDTM", "side": "buy", "trade_id": "first"},
        {"side": "sell"},
        "bad-row",
        {"symbol": "BTCUSDTM", "side": "sell", "trade_id": "second"},
        {"symbol": "ETHUSDTM", "side": "buy", "trade_id": "third"},
    ]

    manager._sync_map_from_list()

    assert sorted(manager._positions_map) == ["BTCUSDTM", "ETHUSDTM"]
    assert manager.get_position("BTCUSDTM")["trade_id"] == "second"
    assert len(manager.positions) == 2
    assert any(
        "PositionManager: skipped malformed/duplicate positions during map sync"
        in record.message
        for record in caplog.records
    )


def test_update_position_preserves_identity_fields():
    manager = PositionManager()
    order = {
        "symbol": "BTCUSDTM",
        "side": "buy",
        "amount": 1,
        "price": 100.0,
        "timestamp": 1,
        "strategy": "TrendFollowing",
        "entry_main_strategy": "TrendFollowing",
        "selection_source": "entry_symbol_strategy_side_allowlist",
        "canonical_bucket": {
            "canonical_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "bucket_identity_status": "RESOLVED",
            "bucket_identity_reason": "explicit_strategy",
            "symbol": "BTCUSDTM",
            "side": "buy",
            "strategy_identity": "TRENDFOLLOWING",
            "raw_symbol": "BTCUSDTM",
            "raw_strategy": "TrendFollowing",
            "raw_side": "buy",
            "normalized_symbol": "BTCUSDTM",
            "normalized_strategy": "TRENDFOLLOWING",
            "normalized_side": "buy",
            "strategy_source": "strategy",
        },
        "canonical_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
    }

    manager.update_position("BTCUSDTM", order)
    position = manager.get_position("BTCUSDTM")

    assert position["entry_main_strategy"] == "TrendFollowing"
    assert position["selection_source"] == "entry_symbol_strategy_side_allowlist"
    assert position["canonical_bucket_key"] == "BTCUSDTM|TRENDFOLLOWING|buy"
    assert position["canonical_bucket"]["canonical_bucket_key"] == (
        "BTCUSDTM|TRENDFOLLOWING|buy"
    )
