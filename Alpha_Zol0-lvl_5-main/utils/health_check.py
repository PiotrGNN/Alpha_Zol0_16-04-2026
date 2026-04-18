"""
health_check.py – sprawdzanie statusu bota
"""

import json
import logging


def health_check(api_key=None, data=None, bot_status=None):
    status = {}
    status["api_key"] = "OK" if api_key else "MISSING"
    status["data_fresh"] = "OK" if data and len(data) > 0 else "STALE"
    status["bot_alive"] = "OK" if bot_status else "DEAD"
    # Logowanie do logs/health.log w formacie JSON
    try:
        logging.basicConfig(filename="logs/health.log", level=logging.INFO)
        logging.info(json.dumps(status))
    except Exception as e:
        print(f"Health log error: {e}")
    return status


# health_check.py – Walidacja API, ticków, statusu bota


def check_api():
    # Real API health check: ping KuCoin public endpoint
    import requests

    try:
        # Futures-first health ping (KuCoin-only, futures runtime).
        resp = requests.get(
            "https://api-futures.kucoin.com/api/v1/timestamp", timeout=5
        )
        if resp.status_code == 200:
            return True
        return False
    except Exception as e:
        logging.error(f"API health check failed: {e}")
        return False


def _pid_is_running(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        import os

        # POSIX: signal 0 checks existence/permission without killing.
        # On Windows, this may raise; we handle below.
        os.kill(pid, 0)
        return True
    except Exception:
        try:
            import platform
            import subprocess

            if platform.system().lower().startswith("win"):
                # tasklist prints PID column; presence means the process exists.
                out = subprocess.check_output(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                return str(pid) in out
        except Exception:
            logging.debug(
                "health_check: tasklist fallback failed for pid=%s",
                pid,
            )
        return False


def _read_last_line(path: str) -> str | None:
    # Efficient last-line reader; avoids reading 50MB+ decision logs into RAM.
    import os

    try:
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size <= 0:
                return None
            chunk = 4096
            buf = b""
            pos = size
            while pos > 0:
                read = chunk if pos >= chunk else pos
                pos -= read
                f.seek(pos)
                data = f.read(read)
                buf = data + buf
                if b"\n" in data and len(buf) > 0:
                    break
            # Take last non-empty line.
            lines = [ln for ln in buf.splitlines() if ln.strip()]
            if not lines:
                return None
            return lines[-1].decode("utf-8", errors="replace")
    except Exception:
        return None


def check_ticks():
    # Real tick health check: check if last tick is recent
    # (from logs/decision_log.csv)
    import os
    from datetime import datetime, timedelta, timezone

    def _parse_ts(ts):
        try:
            dt = datetime.fromisoformat(ts)
        except Exception:
            try:
                dt = datetime.strptime(
                    ts.split("+")[0].split("Z")[0], "%Y-%m-%dT%H:%M:%S"
                )
            except Exception:
                return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def _recent_decision_from_db(max_age_minutes=5):
        try:
            from core.db_models import SessionLocal, Decision
            from datetime import datetime, timezone, timedelta

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
        except Exception as e:
            logging.error(f"DB tick check failed: {e}")
            return False

    try:
        if not os.path.exists("autopsy/decision_log.csv"):
            return _recent_decision_from_db()
        last_line = _read_last_line("autopsy/decision_log.csv")
        if not last_line:
            return _recent_decision_from_db()
        # Timestamp is before first comma (CSV may contain JSON with commas).
        last_ts = last_line.split(",", 1)[0]
        last_dt = _parse_ts(last_ts)
        if last_dt is None:
            return _recent_decision_from_db()
        if datetime.now(timezone.utc) - last_dt < timedelta(minutes=5):
            return True
        return _recent_decision_from_db()
    except Exception as e:
        logging.error(f"Tick health check failed: {e}")
        return _recent_decision_from_db()


# health_check.py – Walidacja API, ticków, statusu bota


def check_bot_status():
    # Real bot status: check if bot process is running (pid file).
    # Decision freshness is tracked separately by check_ticks().
    import os
    from datetime import datetime, timezone

    def _parse_ts(ts):
        try:
            dt = datetime.fromisoformat(ts)
        except Exception:
            try:
                dt = datetime.strptime(
                    ts.split("+")[0].split("Z")[0], "%Y-%m-%dT%H:%M:%S"
                )
            except Exception:
                return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def _recent_decision_from_db(max_age_minutes=5):
        try:
            from core.db_models import SessionLocal, Decision
            from datetime import datetime, timezone, timedelta

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
        except Exception as e:
            logging.error(f"DB bot check failed: {e}")
            return False

    try:
        # Check for PID file
        pid_file = "bot.pid"
        if not os.path.exists(pid_file):
            return _recent_decision_from_db()
        try:
            with open(pid_file, "r", encoding="utf-8") as f:
                pid = int((f.readline() or "").strip() or "0")
        except Exception:
            pid = 0
        if pid and _pid_is_running(pid):
            return True

        # If pidfile exists but process isn't running, fall back to DB activity.
        # This keeps behavior reasonable if pid file is stale.
        return _recent_decision_from_db()
    except Exception as e:
        import logging

        logging.error(f"Bot status check failed: {e}")
        return _recent_decision_from_db()
