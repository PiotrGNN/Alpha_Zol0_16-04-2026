# Orchestrator.py – zbiera decyzje od agentów i loguje voting breakdown
import logging

from agents.AuditAgent import AuditAgent
from agents.ExecutionAgent import ExecutionAgent
from agents.RiskAgent import RiskAgent
from agents.TrendAgent import TrendAgent


class Orchestrator:
    def __init__(self):
        self.agents = {
            "trend": TrendAgent(),
            "risk": RiskAgent(),
            "execution": ExecutionAgent(),
            "audit": AuditAgent(),
        }

    def collect_votes(self, data: dict) -> dict:
        votes = {}
        votes["trend"] = self.agents["trend"].vote(data.get("market_data", {}))
        votes["risk"] = self.agents["risk"].vote(data.get("risk_data", {}))
        votes["execution"] = self.agents["execution"].vote(data.get("exec_data", {}))
        votes["audit"] = self.agents["audit"].vote(data.get("audit_data", {}))
        logging.info(f"Orchestrator: voting breakdown: {votes}")
        return votes

    def decide(self, votes: dict) -> str:
        # Proste głosowanie: większość 'buy' lub 'sell', inaczej 'wait'
        buy_votes = sum(1 for v in votes.values() if v == "buy")
        sell_votes = sum(1 for v in votes.values() if v == "sell")
        if buy_votes > sell_votes and buy_votes > 1:
            decision = "buy"
        elif sell_votes > buy_votes and sell_votes > 1:
            decision = "sell"
        else:
            decision = "wait"
        logging.info(f"Orchestrator: final decision: {decision}")
        return decision
