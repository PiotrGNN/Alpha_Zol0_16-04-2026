import asyncio
import inspect
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List


class SwarmSyncDistributed:
    def __init__(self):
        self.nodes: List[Dict[str, Any]] = []
        self.last_sync_time = None
        self.error_count = 0

    def register_node(
        self, node: Callable, name: str = None, metadata: Dict[str, Any] = None
    ):
        """Zarejestruj nowego agenta (funkcję lub obiekt callable)"""
        entry = {
            "name": name or getattr(node, "__name__", "unnamed"),
            "node": node,
            "meta": metadata or {},
        }
        self.nodes.append(entry)
        logging.info(f"[Swarm] Node registered: {entry['name']}")

    async def _invoke_node(self, node_callable: Callable, message: Any, name: str):
        """Obsługa synchronicznych i asynchronicznych node'ów"""
        try:
            if inspect.iscoroutinefunction(node_callable):
                await node_callable(message)
            else:
                node_callable(message)
            logging.info(f"[Swarm] Message delivered to {name}")
        except Exception as e:
            logging.error(f"[Swarm] Failed to sync with {name}: {e}")
            self.error_count += 1

    async def broadcast(
        self,
        message: Any,
        filter_fn: Callable[[Dict[str, Any]], bool] = None,
    ):
        """Rozesłanie wiadomości do wszystkich agentów
        (z opcjonalnym filtrem).
        """
        n = len(self.nodes)
        logging.info(f"[Swarm] Broadcasting to {n} nodes")
        tasks = []
        for entry in self.nodes:
            if filter_fn and not filter_fn(entry):
                continue
            node = entry["node"]
            name = entry["name"]
            tasks.append(self._invoke_node(node, message, name))
        await asyncio.gather(*tasks, return_exceptions=True)
        self.last_sync_time = datetime.now(timezone.utc).isoformat()

    async def sync(self, message: Dict[str, Any] = None):
        """Główna synchronizacja wszystkich agentów"""
        logging.info(f"[Swarm] Syncing {len(self.nodes)} nodes")
        await self.broadcast(message or {"type": "ping"})
        logging.info(f"[Swarm] Sync complete (errors: {self.error_count})")

    def get_node_names(self) -> List[str]:
        """Lista nazw zarejestrowanych agentów"""
        return [entry["name"] for entry in self.nodes]

    def get_status(self) -> Dict[str, Any]:
        """Status całego roju"""
        return {
            "registered_nodes": len(self.nodes),
            "last_sync": self.last_sync_time,
            "errors": self.error_count,
            "nodes": [entry["name"] for entry in self.nodes],
        }
