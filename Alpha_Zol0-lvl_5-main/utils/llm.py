"""
Offline LLM shim for MetaStrategyRouter.
Provides deterministic, non-network routing output.
"""

import logging
import re

logger = logging.getLogger(__name__)
_warned = False


def ask_llm(prompt: str, model: str = None) -> str:
    """
    Return a deterministic strategy selection based on the prompt.
    This avoids network calls and keeps routing functional.
    """
    global _warned
    if not _warned:
        logger.warning("utils.llm.ask_llm: using offline fallback (no network).")
        _warned = True
    strategy = "Universal"
    try:
        match = re.search(r"\[(.*?)\]", prompt, flags=re.S)
        if match:
            raw = match.group(1)
            parts = [p.strip().strip("'\"") for p in raw.split(",") if p.strip()]
            if parts:
                strategy = parts[0]
    except Exception:
        strategy = "Universal"
    return f"STRATEGY: {strategy}\nREASON: offline_fallback"
