import json

from core.PositionManager import PositionManager
from portfolio.PortfolioNFT import PortfolioNFT


class _RecordingNFT:
    def __init__(self):
        self.calls = []

    def mint_strategy_snapshot(self, **kwargs):
        self.calls.append(kwargs)
        return {"hash": f"snapshot-{len(self.calls)}"}


def test_portfolio_nft_mints_strategy_snapshot_and_logs(tmp_path):
    nft = PortfolioNFT(log_path=str(tmp_path / "portfolio_nft.jsonl"))

    minted = nft.mint_strategy_snapshot(
        event="position_open",
        position={"symbol": "BTCUSDTM", "strategy": "TrendFollowing"},
        active_positions=[{"symbol": "BTCUSDTM", "side": "buy"}],
        closed_positions=[],
    )

    assert minted["snapshot_type"] == "strategy_snapshot"
    assert minted["metadata"]["strategy"] == "TrendFollowing"
    logged = (tmp_path / "portfolio_nft.jsonl").read_text(encoding="utf-8")
    assert json.loads(logged.splitlines()[-1])["hash"] == minted["hash"]


def test_position_manager_emits_portfolio_snapshots_on_open_and_close():
    recorder = _RecordingNFT()
    manager = PositionManager(portfolio_nft=recorder)

    manager.open_position(
        {
            "symbol": "BTCUSDTM",
            "side": "buy",
            "amount": 1.0,
            "entry_price": 100.0,
            "timestamp": "2026-04-18T00:00:00Z",
            "strategy": "TrendFollowing",
        }
    )
    manager.close_position("BTCUSDTM", timestamp="2026-04-18T00:01:00Z", price=101.0)

    assert [call["event"] for call in recorder.calls] == [
        "position_open",
        "position_close",
    ]
    assert recorder.calls[0]["position"]["symbol"] == "BTCUSDTM"
    assert recorder.calls[1]["closed_positions"][-1]["symbol"] == "BTCUSDTM"
