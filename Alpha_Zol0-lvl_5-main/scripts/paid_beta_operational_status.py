from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from paid_beta.config import settings
from paid_beta.database import SessionLocal
from paid_beta.economics_models import EconomicsPeriod
from paid_beta.models import Subscription, WebhookEvent
from paid_beta.trading_metrics import load_scorecard


def _parse_generated_at(scorecard: dict[str, Any] | None) -> datetime | None:
    if not scorecard:
        return None
    value = ((scorecard.get("metadata") or {}).get("generated_at"))
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def collect_status(
    *,
    now: datetime | None = None,
    economics_max_lag_days: int = 8,
    scorecard_max_age_days: int = 7,
    health_url: str = "",
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    blockers: list[str] = []
    db = SessionLocal()
    try:
        latest_period = (
            db.query(EconomicsPeriod)
            .order_by(EconomicsPeriod.period_end.desc())
            .first()
        )
        unprocessed_webhooks = (
            db.query(WebhookEvent)
            .filter(WebhookEvent.processed.is_(False))
            .count()
        )
        failed_payments = (
            db.query(Subscription)
            .filter(Subscription.status.in_(("past_due", "unpaid")))
            .count()
        )
    finally:
        db.close()

    latest_period_end = latest_period.period_end if latest_period else None
    if latest_period_end is None:
        blockers.append("WEEKLY_ECONOMICS_MISSING")
    elif (now.date() - latest_period_end).days > economics_max_lag_days:
        blockers.append("WEEKLY_ECONOMICS_STALE")
    if unprocessed_webhooks:
        blockers.append("UNPROCESSED_WEBHOOKS_PRESENT")
    if failed_payments:
        blockers.append("FAILED_PAYMENTS_PRESENT")

    scorecard_path = Path(settings.trading_scorecard_path)
    scorecard = load_scorecard(scorecard_path)
    generated_at = _parse_generated_at(scorecard)
    if generated_at is None:
        blockers.append("FRESH_SCORECARD_MISSING")
    elif now - generated_at > timedelta(days=scorecard_max_age_days):
        blockers.append("SCORECARD_STALE")

    health: dict[str, Any] = {"requested": bool(health_url), "passed": None}
    if health_url:
        try:
            with urllib.request.urlopen(
                health_url.rstrip("/") + "/health", timeout=15
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
            passed = (
                response.status == 200
                and payload.get("status") == "ok"
                and payload.get("public_live_trading") is False
            )
        except (OSError, ValueError, urllib.error.URLError):
            passed = False
        health["passed"] = passed
        if not passed:
            blockers.append("HTTPS_HEALTH_FAILED")

    return {
        "status": "PASS" if not blockers else "BLOCKED",
        "blockers": sorted(set(blockers)),
        "latest_economics_period_end": (
            latest_period_end.isoformat() if latest_period_end else None
        ),
        "unprocessed_webhook_count": unprocessed_webhooks,
        "failed_payment_subscription_count": failed_payments,
        "scorecard_generated_at": (
            generated_at.isoformat() if generated_at else None
        ),
        "health": health,
        "public_live_trading": False,
        "profitability_claim_allowed": False,
        "checked_at": now.isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed paid-beta operational status"
    )
    parser.add_argument("--health-url", default="")
    parser.add_argument("--json-output", default="")
    parser.add_argument("--economics-max-lag-days", type=int, default=8)
    parser.add_argument("--scorecard-max-age-days", type=int, default=7)
    args = parser.parse_args()

    try:
        report = collect_status(
            economics_max_lag_days=args.economics_max_lag_days,
            scorecard_max_age_days=args.scorecard_max_age_days,
            health_url=args.health_url,
        )
    except Exception as exc:
        report = {
            "status": "FAILED",
            "blockers": ["OPERATIONAL_STATUS_EXCEPTION"],
            "detail": f"{type(exc).__name__}: status collection failed",
            "public_live_trading": False,
            "profitability_claim_allowed": False,
        }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.json_output:
        Path(args.json_output).write_text(rendered + "\n", encoding="utf-8")
    if report["status"] == "PASS":
        return 0
    return 2 if report["status"] == "BLOCKED" else 1


if __name__ == "__main__":
    sys.exit(main())
