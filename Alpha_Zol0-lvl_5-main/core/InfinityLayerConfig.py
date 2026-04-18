# InfinityLayerConfig.py – konfiguracja i parametryzacja warstwy ∞
import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class InfinityLayerConfig:
    def __init__(self, config_path: str = None):
        self.config: Dict[str, Any] = {}
        if config_path:
            self.load(config_path)

    def load(self, path: str):
        try:
            with open(path, "r") as f:
                self.config = json.load(f)
            logging.info(f"InfinityLayerConfig: loaded config from {path}")
        except Exception as e:
            logging.error(f"InfinityLayerConfig: failed to load {path}: {e}")

    def get(self, key: str, default=None):
        return self.config.get(key, default)

    def set(self, key: str, value: Any):
        self.config[key] = value
        logging.info(f"InfinityLayerConfig: set {key}={value}")

    def save(self, path: str):
        try:
            with open(path, "w") as f:
                json.dump(self.config, f, indent=2)
            logging.info(f"InfinityLayerConfig: saved config to {path}")
        except Exception as e:
            logging.error(f"InfinityLayerConfig: failed to save {path}: {e}")
