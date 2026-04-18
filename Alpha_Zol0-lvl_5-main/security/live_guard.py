# live_guard.py – centralized LIVE arming gate (KuCoin-only)
import os
from pathlib import Path

LIVE_APPROVAL_PHRASE = "I_UNDERSTAND_LIVE_RISK"


def _read_live_approval() -> str:
    """Read LIVE approval from env or secret file (no logging of contents)."""
    env_val = os.getenv("LIVE_APPROVAL", "")
    if env_val:
        return env_val.strip()
    secret_paths = (
        "/run/secrets/LIVE_APPROVAL",
        "/run/secrets/live_approval.txt",
        "secrets/live_approval.txt",
        "../secrets/live_approval.txt",
    )
    for path in secret_paths:
        try:
            p = Path(path)
            if p.is_file():
                return p.read_text(encoding="utf-8").strip()
        except Exception:
            # Ignore read errors for safety; caller handles missing approval.
            continue
    return ""


def is_live_armed() -> tuple[bool, str]:
    """
    Multi-step LIVE arming gate.
    LIVE trading is enabled only when ALL conditions are met.
    """
    if os.getenv("LIVE", "0") != "1":
        return False, "LIVE is disabled"
    if os.getenv("LIVE_ARMED", "0") != "1":
        return False, "LIVE_ARMED not set"
    approval = _read_live_approval()
    if approval != LIVE_APPROVAL_PHRASE:
        return False, "LIVE_APPROVAL missing or invalid"
    if not os.getenv("ZOL0_TOKEN"):
        return False, "ZOL0_TOKEN missing"
    if not os.getenv("KUCOIN_API_KEY"):
        return False, "KUCOIN_API_KEY missing"
    if not os.getenv("KUCOIN_API_SECRET"):
        return False, "KUCOIN_API_SECRET missing"
    if not os.getenv("KUCOIN_API_PASSPHRASE"):
        return False, "KUCOIN_API_PASSPHRASE missing"
    return True, "LIVE armed"
