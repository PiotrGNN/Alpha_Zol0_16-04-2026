# GovernanceLayer.py – głosowanie i audyt strategii przez agentów/użytkowników
import logging

logger = logging.getLogger(__name__)


class GovernanceLayer:
    def __init__(self):
        self.roles = {}
        self.votes = {}

    def assign_role(self, user, role):
        self.roles[user] = role
        logger.info(f"GovernanceLayer: assigned {role} to {user}")

    def vote(self, user, strategy_id, decision):
        if strategy_id not in self.votes:
            self.votes[strategy_id] = {}
        self.votes[strategy_id][user] = decision
        logger.info(f"GovernanceLayer: {user} voted {decision} for {strategy_id}")

    def audit_strategy(self, strategy_id):
        votes = self.votes.get(strategy_id, {})
        tally = {d: list(votes.values()).count(d) for d in set(votes.values())}
        logging.info(f"GovernanceLayer: audit for {strategy_id}: {tally}")
        return tally
