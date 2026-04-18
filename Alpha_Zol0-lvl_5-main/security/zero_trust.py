# zero_trust.py – Zero-Trust Architecture

import os


def validate_input(data):
    """Require a non-empty dict; reject None/empty payloads."""
    if data is None:
        return False
    if not isinstance(data, dict):
        return False
    if not data:
        return False
    return True


def authorize(token):
    # Simple token-based authorization
    expected = str(os.getenv("ZOL0_TOKEN") or "").strip()
    candidate = str(token or "").strip()
    return bool(expected) and bool(candidate) and candidate == expected


def log_event(event):
    # Log event to security.log (ensure logs directory exists)
    try:
        from pathlib import Path
        import logging

        Path("logs").mkdir(exist_ok=True)
        with open("logs/security.log", "a", encoding="utf-8") as f:
            f.write(f"SECURITY EVENT: {event}\n")
        logging.info(f"SECURITY EVENT: {event}")
        print(f"SECURITY EVENT: {event}")
    except Exception as e:
        # Fallback: print error and continue (do not crash PAPER mode)
        print(f"SECURITY EVENT (FAILED LOGGING): {event} | ERROR: {e}")
