# ZoL0 LEVEL 0
# config_loader.py – Ładowanie plików YAML
"""Strict YAML configuration loading with fail-closed env substitution."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


def _resolve_env_placeholder(value: str) -> str:
    """Resolve a strict ``${VAR}`` placeholder from the environment."""
    env_var = value[2:-1]
    if not env_var:
        raise ValueError("Empty environment variable placeholder in config")
    if env_var not in os.environ:
        raise KeyError(f"Missing required environment variable: {env_var}")
    return os.environ[env_var]


def _substitute_env(value: Any) -> Any:
    """Recursively substitute strict env placeholders in config values."""
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        return _resolve_env_placeholder(value)
    if isinstance(value, dict):
        return {key: _substitute_env(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_substitute_env(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_substitute_env(item) for item in value)
    return value


def load_config(path):
    """
    Load a YAML config file and return a mapping.

    Missing files, empty documents, and non-mapping top-level YAML values are
    rejected so callers fail closed instead of silently falling back to a
    fabricated runtime profile.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if config is None:
        raise ValueError(f"Config file is empty: {path}")
    if not isinstance(config, dict):
        raise TypeError(
            f"Config file must contain a mapping at top level: {path}"
        )
    return _substitute_env(config)
