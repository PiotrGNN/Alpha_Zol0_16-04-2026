import datetime
import importlib
from datetime import timezone
from core.db_models import DATABASE_URL, SessionLocal, Decision, Equity, LogEntry
from sqlalchemy import desc
import logging
import os
import math
import time


_DEFAULT_DATABASE_URL = DATABASE_URL
_DEFAULT_SESSION_LOCAL = SessionLocal
_DEFAULT_DECISION = Decision
_DEFAULT_EQUITY = Equity
_DEFAULT_LOGENTRY = LogEntry


def _canonical_post_promotion_readback_reason_code(outcome: str) -> str:
    if outcome == "missing":
        return "canonical_post_promotion_readback_missing"
    if outcome == "error":
        return "canonical_post_promotion_readback_error"
    return "canonical_post_promotion_readback_unknown"


def _sync_db_bindings() -> None:
    global DATABASE_URL, SessionLocal, Decision, Equity, LogEntry

    try:
        db_models = importlib.import_module("core.db_models")
    except Exception:
        return

    if globals().get("SessionLocal") is _DEFAULT_SESSION_LOCAL:
        SessionLocal = db_models.SessionLocal
    if globals().get("Decision") is _DEFAULT_DECISION:
        Decision = db_models.Decision
    if globals().get("Equity") is _DEFAULT_EQUITY:
        Equity = db_models.Equity
    if globals().get("LogEntry") is _DEFAULT_LOGENTRY:
        LogEntry = db_models.LogEntry
    if globals().get("DATABASE_URL") == _DEFAULT_DATABASE_URL:
        DATABASE_URL = db_models.DATABASE_URL


def _safe_log_db_event(event: str) -> None:
    try:
        from security.zero_trust import log_event

        log_event(event)
    except Exception:
        logging.warning("DB security event logging unavailable: %s", event)


def _authorize_db_write(event: str) -> bool:
    try:
        from security.zero_trust import authorize

        token = os.environ.get("ZOL0_TOKEN")
        if not authorize(token):
            _safe_log_db_event(f"DB_WRITE_BLOCKED:{event.upper()}:UNAUTHORIZED")
            logging.warning("DB write blocked: unauthorized")
            return False
    except Exception:
        # If auth subsystem unavailable, block for safety
        _safe_log_db_event(
            f"DB_WRITE_BLOCKED:{event.upper()}:AUTH_SUBSYSTEM_UNAVAILABLE"
        )
        logging.warning("DB write blocked: auth subsystem unavailable")
        return False
    return True


def ms_to_datetime(ts):
    if ts is None:
        return None
    if isinstance(ts, bool):
        logging.debug("ms_to_datetime: boolean timestamp rejected ts=%s", ts)
        return None
    if isinstance(ts, datetime.datetime):
        # Ensure timezone-aware; assume UTC when missing
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts
    try:
        # If ts is in ms (int/float, > 1e10), convert to seconds
        if isinstance(ts, (int, float)) and ts > 1e10:
            return datetime.datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
        # If ts is in seconds (int/float), convert directly
        if isinstance(ts, (int, float)):
            return datetime.datetime.fromtimestamp(ts, tz=timezone.utc)
        # If ts is a string, try parsing
        if isinstance(ts, str):
            # Try ISO format first
            try:
                parsed = datetime.datetime.fromisoformat(ts)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed
            except Exception as exc:
                logging.debug(
                    "ms_to_datetime: ISO parse failed ts=%s error=%s",
                    ts,
                    exc,
                )
            # Try as float (ms or s)
            try:
                tsf = float(ts)
                if tsf > 1e10:
                    return datetime.datetime.fromtimestamp(
                        tsf / 1000.0, tz=timezone.utc
                    )
                return datetime.datetime.fromtimestamp(tsf, tz=timezone.utc)
            except Exception as exc:
                logging.debug(
                    "ms_to_datetime: float parse failed ts=%s error=%s",
                    ts,
                    exc,
                )
    except Exception as exc:
        logging.debug("ms_to_datetime: outer parse failed ts=%s error=%s", ts, exc)

    return None


def _coerce_finite_float(value):
    if isinstance(value, bool):
        return None
    try:
        coerced = float(value)
    except Exception:
        return None
    if not math.isfinite(coerced):
        return None
    return float(coerced)


def save_decision_to_db(timestamp, decision, details=None):
    if not _authorize_db_write("decision"):
        return False
    _sync_db_bindings()
    db = None
    # Validate details payload before writing to DB; if invalid, skip write
    try:
        val_ok = True
        details_to_check = {}
        try:
            from security.zero_trust import validate_input
            import json

            if isinstance(details, str):
                try:
                    details_to_check = json.loads(details)
                except Exception:
                    details_to_check = {}
            elif isinstance(details, dict):
                details_to_check = details
            else:
                details_to_check = {"action": decision}
            val_ok = validate_input(details_to_check)
        except Exception:
            _safe_log_db_event(
                "DB_WRITE_BLOCKED:DECISION:VALIDATION_SUBSYSTEM_UNAVAILABLE"
            )
            logging.warning(
                "save_decision_to_db: validate_input unavailable, blocking DB write"
            )
            return False
        if not val_ok:
            _safe_log_db_event("DB_WRITE_BLOCKED:DECISION:INVALID_PAYLOAD")
            logging.warning(
                "save_decision_to_db: invalid payload, skipping " "DB write"
            )
            return False
        timestamp_dt = ms_to_datetime(timestamp)
        if timestamp_dt is None:
            logging.warning("save_decision_to_db: invalid timestamp value")
            return False
        db = SessionLocal()
        # Optional throttle to reduce duplicate decisions
        try:
            throttle = int(os.environ.get("DECISION_THROTTLE_SEC", "0"))
        except Exception:
            throttle = 0
        if throttle > 0:
            try:
                last = db.query(Decision).order_by(desc(Decision.timestamp)).first()
                if last and last.decision == decision:
                    last_details = last.details or ""
                    cur_details = details or ""
                    if last_details == cur_details:
                        cur_ts = timestamp_dt
                        if (
                            last.timestamp
                            and abs((cur_ts - last.timestamp).total_seconds())
                            <= throttle
                        ):
                            return False
            except Exception:
                # If throttle check fails, proceed with write
                pass
        dec = Decision(
            timestamp=timestamp_dt,
            decision=decision,
            details=details,
        )
        db.add(dec)
        db.commit()
        return True
    except Exception as e:
        logging.warning(f"save_decision_to_db: DB unavailable or error: {e}")
        return False
    finally:
        if db is not None:
            try:
                db.close()
            except Exception as exc:
                logging.debug("save_decision_to_db: db.close failed error=%s", exc)


def save_equity_to_db(timestamp, equity, pnl):
    if not _authorize_db_write("equity"):
        return False
    _sync_db_bindings()
    db = None
    try:
        eq_val = _coerce_finite_float(equity)
        if eq_val is None:
            logging.warning("save_equity_to_db: invalid equity value")
            return False
        pnl_val = _coerce_finite_float(pnl)
        if pnl_val is None:
            logging.warning("save_equity_to_db: invalid pnl value")
            return False
        try:
            max_usdt = float(os.environ.get("EQUITY_MAX_USDT", "1000000"))
        except Exception:
            max_usdt = 1000000.0
        if not math.isfinite(eq_val) or abs(eq_val) > max_usdt:
            logging.warning(
                f"save_equity_to_db: equity out of range ({eq_val}); skipped"
            )
            return False
        timestamp_dt = ms_to_datetime(timestamp)
        if timestamp_dt is None:
            logging.warning("save_equity_to_db: invalid timestamp value")
            return False
        db = SessionLocal()
        eq = Equity(
            timestamp=timestamp_dt,
            equity=eq_val,
            pnl=pnl_val,
        )
        db.add(eq)
        db.commit()
        return True
    except Exception as e:
        logging.warning(f"save_equity_to_db: DB unavailable or error: {e}")
        return False
    finally:
        if db is not None:
            try:
                db.close()
            except Exception as exc:
                logging.debug("save_equity_to_db: db.close failed error=%s", exc)


def save_log_to_db(event, details=None):
    if not _authorize_db_write("log"):
        return False
    _sync_db_bindings()
    db = None
    database_url = str(DATABASE_URL or "")
    is_sqlite = database_url.startswith("sqlite")
    sqlite_retry_enabled = is_sqlite and os.environ.get("LIVE", "0") != "1"
    lock_retry_budget = 8 if sqlite_retry_enabled else 1
    try:
        # Ensure details is a JSON/string payload for Postgres compatibility
        try:
            import json

            if isinstance(details, dict):
                details = json.dumps(details)
            elif details is not None and not isinstance(details, str):
                details = str(details)
        except Exception:
            try:
                details = str(details)
            except Exception as exc:
                logging.debug(
                    "save_log_to_db: details stringify failed error=%s",
                    exc,
                )
                details = None

        for attempt_idx in range(lock_retry_budget):
            try:
                if db is not None:
                    try:
                        db.close()
                    except Exception as exc:
                        logging.debug(
                            "save_log_to_db: retry db.close failed error=%s",
                            exc,
                        )
                db = SessionLocal()
                if sqlite_retry_enabled:
                    try:
                        db.connection().exec_driver_sql("PRAGMA busy_timeout = 10000")
                    except Exception as exc:
                        logging.debug(
                            "save_log_to_db: PRAGMA busy_timeout failed error=%s",
                            exc,
                        )
                log = LogEntry(
                    timestamp=ms_to_datetime(datetime.datetime.now(tz=timezone.utc)),
                    event=event,
                    details=details,
                )
                db.add(log)
                db.commit()
                break
            except Exception as e:
                message = str(e)
                is_sqlite_lock = is_sqlite and "database is locked" in message.lower()
                if db is not None:
                    try:
                        db.rollback()
                    except Exception as exc:
                        logging.debug(
                            "save_log_to_db: rollback failed error=%s",
                            exc,
                        )
                if is_sqlite_lock and attempt_idx + 1 < lock_retry_budget:
                    time.sleep(min(0.1 * (2**attempt_idx), 1.5))
                    continue
                raise
        if event == "canonical_explicit_post_promotion_post_invoke_emit_attempt_enter":
            try:
                readback = (
                    db.query(LogEntry)
                    .filter(LogEntry.event == event, LogEntry.details == details)
                    .order_by(desc(LogEntry.id))
                    .first()
                )
                if readback is None:
                    reason_code = _canonical_post_promotion_readback_reason_code(
                        "missing"
                    )
                    logging.warning(
                        (
                            "save_log_to_db: breadcrumb readback failed "
                            "reason_code=%s event=%s"
                        ),
                        reason_code,
                        event,
                    )
                    return True
            except Exception as e:
                reason_code = _canonical_post_promotion_readback_reason_code(
                    "error"
                )
                logging.warning(
                    (
                        "save_log_to_db: breadcrumb readback error "
                        "reason_code=%s event=%s error=%s"
                    ),
                    reason_code,
                    event,
                    e,
                )
                return True
        return True
    except Exception as e:
        logging.warning(f"save_log_to_db: DB unavailable or error: {e}")
        return False
    finally:
        if db is not None:
            try:
                db.close()
            except Exception as exc:
                logging.debug("save_log_to_db: final db.close failed error=%s", exc)
