# OmegaAudit.py – audyt i rejestracja decyzji, logów, zdarzeń dla warstwy ∞
import logging
from datetime import datetime, timezone
from typing import Dict, List


class OmegaAudit:
    def __init__(self):
        self.entries: List[Dict] = []

    def log_decision(
        self,
        agent: str,
        decision: str,
        result: str,
        meta: Dict = None,
    ):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "decision": decision,
            "result": result,
            "meta": meta or {},
        }
        self.entries.append(entry)
        logging.info(f"OmegaAudit: logged {entry}")

    def get_entries(self, agent: str = None):
        if agent:
            return [e for e in self.entries if e["agent"] == agent]
        return self.entries

    def summary(self):
        return {
            "total": len(self.entries),
            "agents": list(set(e["agent"] for e in self.entries)),
        }
