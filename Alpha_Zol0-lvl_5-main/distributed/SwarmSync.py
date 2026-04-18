# SwarmSync.py – synchronizacja i komunikacja AI w rozproszonej sieci
import logging
from typing import List


class SwarmSync:
    def __init__(self):
        self.nodes: List[str] = []
        self.agents = []  # List of callables
        self.synced = False

    def register_node(self, node_id: str):
        if node_id not in self.nodes:
            self.nodes.append(node_id)
            logging.info(f"SwarmSync: node registered {node_id}")

    def register_agent(self, agent_callable):
        if agent_callable not in self.agents:
            self.agents.append(agent_callable)
            logging.info(f"SwarmSync: agent registered {agent_callable}")

    def broadcast(self, msg):
        for agent in self.agents:
            agent(msg)
        logging.info(f"SwarmSync: broadcasted '{msg}' to {len(self.agents)} agents")

    def sync(self):
        if self.nodes or self.agents:
            self.synced = True
            logging.info(
                (
                    f"SwarmSync: sync complete for nodes {self.nodes} "
                    f"and agents {len(self.agents)}"
                )
            )
            return True
        logging.warning("SwarmSync: no nodes or agents to sync")
        return False

    def is_synced(self):
        return self.synced
