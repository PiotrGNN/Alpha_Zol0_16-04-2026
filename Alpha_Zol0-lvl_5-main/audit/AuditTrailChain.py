# AuditTrailChain.py – zapis hash decyzji na blockchainie (L2)

import hashlib
import logging
from datetime import datetime, timezone

logger = logging.getLogger("AuditTrailChain")


class AuditTrailChain:
    def __init__(self):
        self.trail = []

    def record_decision(self, model_hash, params, result):
        timestamp = datetime.now(timezone.utc).isoformat()
        data = f"{model_hash}|{params}|{result}|{timestamp}"
        decision_hash = hashlib.sha256(data.encode()).hexdigest()
        self.trail.append({"hash": decision_hash, "data": data})
        logger.info(f"AuditTrailChain: decision hash recorded {decision_hash}")
        # Mock: zapis na Arbitrum/Polygon
        return decision_hash
