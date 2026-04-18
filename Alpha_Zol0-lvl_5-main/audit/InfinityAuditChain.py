# InfinityAuditChain.py – łańcuch audytowy dla warstwy ∞

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger("InfinityAuditChain")


class InfinityAuditChain:
    def __init__(self):
        self.chain: List[Dict[str, Any]] = []

    def log_event(
        self,
        agent: str,
        event: str,
        details: Dict[str, Any] = None,
    ):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "event": event,
            "details": details or {},
        }
        self.chain.append(entry)
        logging.info(f"InfinityAuditChain: logged {entry}")

    def get_chain(self, agent: str = None):
        if agent:
            return [e for e in self.chain if e["agent"] == agent]
        return self.chain

    def summary(self):
        return {
            "total": len(self.chain),
            "agents": list(set(e["agent"] for e in self.chain)),
        }
