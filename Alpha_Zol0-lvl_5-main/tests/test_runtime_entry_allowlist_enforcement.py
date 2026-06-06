import core.BotCore as botcore


XRP_SELL_ALLOWLIST = {
    "XRPUSDTM:MOMENTUM:sell",
    "XRPUSDTM:TRENDFOLLOWING:sell",
}


def test_paper_exact_symbol_strategy_side_allowlist_blocks_foreign_buckets():
    for symbol, strategy, side in (
        ("ETHUSDTM", "Momentum", "buy"),
        ("BTCUSDTM", "Momentum", "sell"),
        ("BNBUSDTM", "TrendFollowing", "buy"),
    ):
        decision = botcore._entry_symbol_strategy_side_allowlist_gate(
            symbol=symbol,
            strategy=strategy,
            side=side,
            allowlist=XRP_SELL_ALLOWLIST,
            live_mode=False,
        )
        assert decision["allowed"] is False
        assert decision["reason"] == "symbol_strategy_side_allowlist"
        assert decision["candidate_key"] not in decision["allowlist"]


def test_paper_exact_symbol_strategy_side_allowlist_allows_xrp_sell_buckets():
    for strategy in ("Momentum", "TrendFollowing"):
        decision = botcore._entry_symbol_strategy_side_allowlist_gate(
            symbol="XRPUSDTM",
            strategy=strategy,
            side="sell",
            allowlist=XRP_SELL_ALLOWLIST,
            live_mode=False,
        )
        assert decision["allowed"] is True
        assert decision["reason"] is None
        assert decision["candidate_key"] in decision["allowlist"]

