# PortfolioNFT.py – tokenizacja portfeli jako NFT
import hashlib
import json
import logging
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class PortfolioNFT:
    def __init__(self, log_path: str | None = None):
        self.nfts: Dict[str, Dict[str, Any]] = {}
        self.log_path = Path(log_path) if log_path else None

    @staticmethod
    def _clone(value):
        return deepcopy(value)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _write_log(self, nft: Dict[str, Any]) -> None:
        if self.log_path is None:
            return
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(nft, ensure_ascii=False, default=str) + "\n")
        except Exception as exc:
            logging.warning("PortfolioNFT: snapshot log write failed: %s", exc)

    def mint(
        self,
        portfolio: Dict[str, Any],
        *,
        snapshot_type: str = "portfolio_state",
        metadata: Dict[str, Any] | None = None,
    ):
        snapshot = self._clone(portfolio)
        data = json.dumps(snapshot, sort_keys=True, default=str, ensure_ascii=True)
        nft_hash = hashlib.sha256(data.encode("utf-8")).hexdigest()
        nft = {
            "hash": nft_hash,
            "portfolio": snapshot,
            "token_type": "ERC721",
            "snapshot_type": snapshot_type,
            "access_token": nft_hash[:16],
            "minted_at": self._now_iso(),
        }
        if metadata is not None:
            nft["metadata"] = self._clone(metadata)
        self.nfts[nft_hash] = nft
        self._write_log(nft)
        logging.info("PortfolioNFT: minted NFT %s type=%s", nft_hash, snapshot_type)
        return self._clone(nft)

    def mint_strategy_snapshot(
        self,
        *,
        event: str,
        position: Dict[str, Any] | None = None,
        active_positions=None,
        closed_positions=None,
        optimizer_result: Dict[str, Any] | None = None,
    ):
        active_positions = list(active_positions or [])
        closed_positions = list(closed_positions or [])
        snapshot = {
            "event": event,
            "position": self._clone(position) if isinstance(position, dict) else None,
            "active_positions": self._clone(active_positions),
            "closed_positions_count": len(closed_positions),
        }
        if closed_positions:
            snapshot["latest_closed_position"] = self._clone(closed_positions[-1])
        if optimizer_result is not None:
            snapshot["optimizer_result"] = self._clone(optimizer_result)

        metadata = {
            "event": event,
            "symbol": position.get("symbol") if isinstance(position, dict) else None,
            "strategy": (
                position.get("strategy") if isinstance(position, dict) else None
            ),
            "active_positions_count": len(active_positions),
            "closed_positions_count": len(closed_positions),
        }
        return self.mint(
            snapshot,
            snapshot_type="strategy_snapshot",
            metadata=metadata,
        )

    def get_nft(self, nft_hash: str):
        nft = self.nfts.get(nft_hash)
        return self._clone(nft) if nft is not None else None
