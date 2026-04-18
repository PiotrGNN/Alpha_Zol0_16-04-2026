"""Seed the Postgres DB with minimal development data.

Usage:
  python scripts/seed_dev.py

This script is safe to run repeatedly: it will only seed when tables are empty.
"""

from datetime import datetime, timedelta, timezone
import json

from core.db_models import SessionLocal, init_db, Equity, Decision


def seed():
    init_db()
    db = SessionLocal()
    try:
        equity_count = db.query(Equity).count()
        decision_count = db.query(Decision).count()
        if equity_count > 0 or decision_count > 0:
            print("DB already has data — skipping seeding.")
            return

        print("Seeding DB with sample equity and decision data...")
        now = datetime.now(tz=timezone.utc)
        # Create 10 equity points spaced 1 hour apart
        for i in range(10):
            ts = now - timedelta(hours=(10 - i))
            eq = Equity(timestamp=ts, equity=10000 + i * 50.0, pnl=(i * 50.0))
            db.add(eq)

        # Add a sample decision
        details = json.dumps({"symbol": "BTC-USDT", "amount": 0.1})
        dec = Decision(timestamp=now, decision="buy", details=details)
        db.add(dec)

        db.commit()
        print("Seeding complete")
    except Exception as e:
        print(f"Seeding failed: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
