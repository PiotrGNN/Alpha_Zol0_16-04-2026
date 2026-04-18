# DistributedOrchestrator.py – koordynacja AI w rozproszonej sieci
import logging
from typing import Callable, List


class DistributedOrchestrator:
    def __init__(self):
        self.nodes: List[Callable] = []
        self.status: List[str] = []

    def register_node(self, node: Callable):
        self.nodes.append(node)
        logging.info(
            (
                "DistributedOrchestrator: node registered "
                f"{getattr(node, '__name__', str(node))}"
            )
        )

    def orchestrate(self, message):
        self.status.clear()
        for node in self.nodes:
            try:
                node(message)
                self.status.append(f"{getattr(node, '__name__', str(node))}: ok")
                logging.info(
                    (
                        "DistributedOrchestrator: message sent to "
                        f"{getattr(node, '__name__', str(node))}"
                    )
                )
            except Exception as e:
                self.status.append(f"{getattr(node, '__name__', str(node))}: fail {e}")
                logging.error(
                    (
                        f"DistributedOrchestrator: failed to send to "
                        f"{getattr(node, '__name__', str(node))}: {e}"
                    )
                )
        return self.status
