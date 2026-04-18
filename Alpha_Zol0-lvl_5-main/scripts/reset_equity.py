import os
import sys
from core.db_models import SessionLocal, Equity, Decision, LogEntry


def main() -> int:
    if os.environ.get("CONFIRM_EQUITY_RESET") != "1":
        print("Refusing to reset equity. Set CONFIRM_EQUITY_RESET=1 to proceed.")
        return 1
    reset_session = os.environ.get("RESET_SESSION") == "1"
    reset_decisions = reset_session or os.environ.get("RESET_DECISIONS") == "1"
    reset_logs = reset_session or os.environ.get("RESET_LOGS") == "1"
    db = SessionLocal()
    try:
        count = db.query(Equity).count()
        db.query(Equity).delete()
        decisions_deleted = 0
        logs_deleted = 0
        if reset_decisions:
            decisions_deleted = db.query(Decision).count()
            db.query(Decision).delete()
        if reset_logs:
            logs_deleted = db.query(LogEntry).count()
            db.query(LogEntry).delete()
        db.commit()
        print(f"Equity reset OK. Deleted rows: {count}")
        if reset_decisions:
            print(f"Decisions reset OK. Deleted rows: {decisions_deleted}")
        if reset_logs:
            print(f"Logs reset OK. Deleted rows: {logs_deleted}")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"Equity reset failed: {exc}")
        return 2
    finally:
        try:
            db.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
