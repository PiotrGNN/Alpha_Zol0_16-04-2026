# Kill-switch global state
import logging

_active = False


def trigger(reason: str = "unknown"):
    global _active
    _active = True
    logging.error(f"KILL-SWITCH ACTIVATED: {reason}")


def reset():
    global _active
    _active = False


def is_active() -> bool:
    return _active
