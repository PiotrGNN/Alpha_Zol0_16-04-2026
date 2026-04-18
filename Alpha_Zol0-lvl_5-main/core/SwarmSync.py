# SwarmSync.py – synchronizacja i komunikacja pomiędzy agentami w roju
import logging
from typing import Callable, List

logger = logging.getLogger(__name__)


class SwarmSync:
    def __init__(self):
        self.agents: List[Callable] = []

    def register_agent(self, agent: Callable):
        self.agents.append(agent)
        logger.info(f"SwarmSync: registered agent {agent.__name__}")

    def broadcast(self, message):
        for agent in self.agents:
            agent(message)
            logging.info(f"SwarmSync: broadcasted to {agent.__name__}")

    def sync(self):
        logging.info(f"SwarmSync: syncing {len(self.agents)} agents")
        # Advanced sync logic can be implemented here if needed
        return True
