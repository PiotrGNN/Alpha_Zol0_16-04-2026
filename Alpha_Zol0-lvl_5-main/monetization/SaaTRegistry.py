# SaaTRegistry.py – tokenizacja strategii (NFT/ERC1155)
import hashlib
import logging
from typing import Dict


class SaaTRegistry:
    def __init__(self):
        self.registry = {}

    def register_strategy(self, strategy: Dict, performance: Dict):
        # Hash strategii + performance
        data = str(strategy) + str(performance)
        strategy_hash = hashlib.sha256(data.encode()).hexdigest()
        nft = {
            "hash": strategy_hash,
            "performance": performance,
            "token_type": "ERC1155",
            "access_token": strategy_hash[:16],
        }
        self.registry[strategy_hash] = nft
        logging.info(f"SaaTRegistry: strategy registered as NFT {strategy_hash}")
        return nft

    def get_nft(self, strategy_hash):
        return self.registry.get(strategy_hash)
