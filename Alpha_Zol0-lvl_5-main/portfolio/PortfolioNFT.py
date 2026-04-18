# PortfolioNFT.py – tokenizacja portfeli jako NFT
import hashlib
import logging
from typing import Any, Dict


class PortfolioNFT:
    def __init__(self):
        self.nfts: Dict[str, Dict[str, Any]] = {}

    def mint(self, portfolio: Dict[str, Any]):
        data = str(portfolio)
        nft_hash = hashlib.sha256(data.encode()).hexdigest()
        nft = {
            "hash": nft_hash,
            "portfolio": portfolio,
            "token_type": "ERC721",
            "access_token": nft_hash[:16],
        }
        self.nfts[nft_hash] = nft
        logging.info(f"PortfolioNFT: minted NFT {nft_hash}")
        return nft

    def get_nft(self, nft_hash: str):
        return self.nfts.get(nft_hash)
