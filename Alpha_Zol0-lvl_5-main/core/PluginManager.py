# PluginManager.py – zarządzanie pluginami, ładowanie, rejestracja, wywołania
import logging
from typing import Callable, Dict

logger = logging.getLogger(__name__)


class PluginManager:
    def __init__(self):
        self.plugins: Dict[str, Callable] = {}

    def register_plugin(self, name: str, plugin: Callable):
        self.plugins[name] = plugin
        logger.info(f"PluginManager: registered {name}")

    def load_plugin(self, name: str):
        if name in self.plugins:
            logging.info(f"PluginManager: loaded {name}")
            return self.plugins[name]
        logging.warning(f"PluginManager: plugin {name} not found")
        return None

    def call_plugin(self, name: str, *args, **kwargs):
        plugin = self.load_plugin(name)
        if plugin:
            return plugin(*args, **kwargs)
        return None
