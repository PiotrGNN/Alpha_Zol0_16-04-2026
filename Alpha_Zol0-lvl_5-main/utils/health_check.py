"""Runtime health checks for API reachability, tick freshness, and bot activity."""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_API_URL = "https://api-futures.kucoin.com/api/v1/timestamp"
DEFAULT_HEALTH_LOG_PATH = Path("logs/health.log")
DEFAULT_DECISION_LOG_PATHS = (
    Path("autopsy/decision_log.csv"),
    Path("logs/decision_log.csv"),
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_health_log(payload: dict[str, Any]) -> None:
    try:
        DEFAULT_HEALTH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DEFAULT_HEALTH_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception as exc:
        logging.error("Health log error: %s", exc)


def _legacy_override_to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (str, bytes, list, tuple, dict, set)):
        return len(value) > 0
    return bool(value)


def _recent_decision_from_db(max_age_minutes=5):
    try:
        from core.db_models import Decision, SessionLocal

        db = SessionLocal()
        try:
            last = db.query(Decision).order_by(Decision.timestamp.desc()).first()
            if not last:
                return False
            last_dt = last.timestamp
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) - last_dt < timedelta(
                minutes=max_age_minutes
            )
        finally:
            db.close()
    except Exception as exc:
        logging.error("DB health check failed: %s", exc)
        return False


def check_api(url: str = DEFAULT_API_URL, timeout: float = 5.0) -> bool:
    import requests

    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, dict):
            return False
        data = payload.get("data")
        return data not in (None, "", [], {})
    except Exception as exc:
        logging.error("API health check failed: %s", exc)
        return False


def _pid_is_running(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        import os

        os.kill(pid, 0)
        return True
    except Exception:
        try:
            import platform
            import subprocess

            if platform.system().lower().startswith("win"):
                out = subprocess.check_output(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                return str(pid) in out
        except Exception:
            logging.debug("health_check: tasklist fallback failed for pid=%s", pid)
        return False


def _read_last_line(path: str) -> str | None:
    import os

    try:
        if not os.path.exists(path):
            return None
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            if size <= 0:
                return None
            chunk = 4096
            buf = b""
            pos = size
            while pos > 0:
                read = chunk if pos >= chunk else pos
                pos -= read
                handle.seek(pos)
                data = handle.read(read)
                buf = data + buf
                if b"\n" in data and len(buf) > 0:
                    break
            lines = [line for line in buf.splitlines() if line.strip()]
            if not lines:
                return None
            return lines[-1].decode("utf-8", errors="replace")
    except Exception:
        return None


def _parse_ts(ts: str):
    try:
        dt = datetime.fromisoformat(ts)
    except Exception:
        try:
            dt = datetime.strptime(ts.split("+")[0].split("Z")[0], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def check_ticks(decision_log_path=None, max_age_minutes=5):
    candidate_paths = decision_log_path or DEFAULT_DECISION_LOG_PATHS
    if isinstance(candidate_paths, (str, Path)):
        candidate_paths = [candidate_paths]

    try:
        for path in candidate_paths:
            path_obj = Path(path)
            if not path_obj.exists():
                continue
            last_line = _read_last_line(str(path_obj))
            if not last_line:
                continue
            last_ts = last_line.split(",", 1)[0]
            last_dt = _parse_ts(last_ts)
            if last_dt is None:
                continue
            if datetime.now(timezone.utc) - last_dt < timedelta(
                minutes=max_age_minutes
            ):
                return True
        return _recent_decision_from_db(max_age_minutes=max_age_minutes)
    except Exception as exc:
        logging.error("Tick health check failed: %s", exc)
        return _recent_decision_from_db(max_age_minutes=max_age_minutes)


def check_bot_status(pid_file="bot.pid", max_age_minutes=5):
    pid_path = Path(pid_file)
    try:
        if not pid_path.exists():
            return _recent_decision_from_db(max_age_minutes=max_age_minutes)
        try:
            pid = int((pid_path.read_text(encoding="utf-8") or "").strip() or "0")
        except Exception:
            pid = 0
        if pid and _pid_is_running(pid):
            return True
        return _recent_decision_from_db(max_age_minutes=max_age_minutes)
    except Exception as exc:
        logging.error("Bot status check failed: %s", exc)
        return _recent_decision_from_db(max_age_minutes=max_age_minutes)


def health_check(api_key=None, data=None, bot_status=None):
    api_ok = _legacy_override_to_bool(api_key)
    if api_ok is None:
        api_ok = check_api()

    ticks_ok = _legacy_override_to_bool(data)
    if ticks_ok is None:
        ticks_ok = check_ticks()

    bot_ok = _legacy_override_to_bool(bot_status)
    if bot_ok is None:
        bot_ok = check_bot_status()

    payload = {
        "status": "ok" if all((api_ok, ticks_ok, bot_ok)) else "degraded",
        "timestamp": _now_iso(),
        "api": api_ok,
        "ticks": ticks_ok,
        "bot": bot_ok,
        "checks": {
            "api": api_ok,
            "ticks": ticks_ok,
            "bot": bot_ok,
        },
        "api_key": "OK" if api_ok else "MISSING",
        "data_fresh": "OK" if ticks_ok else "STALE",
        "bot_alive": "OK" if bot_ok else "DEAD",
    }
    _append_health_log(payload)
    return payload
