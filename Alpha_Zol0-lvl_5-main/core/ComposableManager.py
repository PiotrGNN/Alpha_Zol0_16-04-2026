# ComposableManager.py – dynamiczne zarządzanie kompozycją strategii i modułów


import logging
from typing import Callable, Dict, List

logger = logging.getLogger("ComposableManager")


class ComposableManager:
    def __init__(self):
        self.modules: Dict[str, Callable] = {}
        self.active: List[str] = []

    def register_module(self, name: str, module: Callable):
        self.modules[name] = module
        logger.info(f"ComposableManager: registered {name}")

    def activate(self, name: str):
        if name in self.modules:
            if name not in self.active:
                self.active.append(name)
            logger.info(f"ComposableManager: activated {name}")
        else:
            logger.error(f"ComposableManager: module {name} not found")

    def deactivate(self, name: str):
        if name in self.active:
            self.active.remove(name)
            logging.info(f"ComposableManager: deactivated {name}")

    def run_active(self, *args, **kwargs):
        results = {}
        for name in self.active:
            results[name] = self.modules[name](*args, **kwargs)
        logging.info(f"ComposableManager: ran active modules {self.active}")
        return results
