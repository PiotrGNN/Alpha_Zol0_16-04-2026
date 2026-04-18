# Tests enforcing KuCoin-only runtime policy
from pathlib import Path

import pytest

from core.MultiChainExecutor import MultiChainExecutor
from platforms.MetaPlatformManager import MetaPlatformManager

RUNTIME_DIRS = ("core", "platforms", "utils", "config")
FORBIDDEN_HOST_TOKENS = ("bybit", "binance", "okx")
FORBIDDEN_ENV_TOKENS = ("BYBIT", "BINANCE", "OKX")


def _iter_runtime_files():
    base = Path(__file__).resolve().parents[1]
    for name in RUNTIME_DIRS:
        root = base / name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() in {".py", ".yaml", ".yml", ".env", ".ini", ".cfg"}:
                yield path


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def test_no_non_kucoin_hosts_in_codepaths():
    offenders = []
    for path in _iter_runtime_files():
        content = _read_text(path).lower()
        if any(token in content for token in FORBIDDEN_HOST_TOKENS):
            offenders.append(str(path))
    assert not offenders, f"Non-KuCoin hosts found in runtime paths: {offenders}"


def test_no_bybit_env_keys_used():
    offenders = []
    for path in _iter_runtime_files():
        content = _read_text(path)
        if any(token in content for token in FORBIDDEN_ENV_TOKENS):
            offenders.append(str(path))
    assert not offenders, f"Non-KuCoin env keys found: {offenders}"


def test_runtime_blocks_non_kucoin_platform():
    mgr = MetaPlatformManager()
    with pytest.raises(ValueError):
        mgr.register_platform("bybit", object())
    with pytest.raises(ValueError):
        mgr.register_platform("okx", object())
    with pytest.raises(ValueError):
        MultiChainExecutor({"binance": object()})
