from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = {
    "period_start",
    "period_end",
    "source",
    "currency",
    "gross_revenue",
    "payment_fees",
    "refunds",
    "hosting_cost",
    "support_cost",
    "acquisition_spend",
    "other_variable_cost",
    "active_customers",
    "new_customers",
    "churned_customers",
    "activated_customers",
    "checkout_started",
    "checkout_completed",
    "failed_payments",
    "recovered_payments",
    "support_minutes",
}


def validate_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED_FIELDS - set(payload))
    if missing:
        errors.append("missing fields: " + ", ".join(missing))
        return errors
    try:
        start = date.fromisoformat(str(payload["period_start"]))
        end = date.fromisoformat(str(payload["period_end"]))
        if (end - start).days != 6:
            errors.append("period must contain exactly 7 calendar days")
    except ValueError:
        errors.append("period_start and period_end must use ISO YYYY-MM-DD")
    if not str(payload.get("source") or "").strip():
        errors.append("source must be non-empty")
    if len(str(payload.get("currency") or "")) != 3:
        errors.append("currency must contain exactly 3 characters")
    numeric_fields = REQUIRED_FIELDS - {"period_start", "period_end", "source", "currency"}
    for field in sorted(numeric_fields):
        value = payload.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            errors.append(f"{field} must be a non-negative number")
    if not errors:
        if payload["checkout_completed"] > payload["checkout_started"]:
            errors.append("checkout_completed exceeds checkout_started")
        if payload["activated_customers"] > payload["new_customers"]:
            errors.append("activated_customers exceeds new_customers")
        if payload["recovered_payments"] > payload["failed_payments"]:
            errors.append("recovered_payments exceeds failed_payments")
    return errors


def submit_payload(*, base_url: str, token: str, payload: dict[str, Any]) -> tuple[str, int]:
    endpoint = base_url.rstrip("/") + "/resources/admin/economics-periods"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
            return "RECORDED", response.status
    except urllib.error.HTTPError as exc:
        exc.read()
        if exc.code == 409:
            return "ALREADY_RECORDED", exc.code
        return "FAILED", exc.code


def main() -> int:
    parser = argparse.ArgumentParser(description="Import one weekly paid-beta economics period")
    parser.add_argument("payload", type=Path, help="JSON file containing one seven-day period")
    parser.add_argument("--base-url", default=os.getenv("PAID_BETA_APP_URL", ""))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        payload = json.loads(args.payload.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "INVALID", "detail": f"{type(exc).__name__}: cannot read payload"}))
        return 2
    if not isinstance(payload, dict):
        print(json.dumps({"status": "INVALID", "detail": "payload must be a JSON object"}))
        return 2

    errors = validate_payload(payload)
    if errors:
        print(json.dumps({"status": "INVALID", "errors": errors}, sort_keys=True))
        return 2

    summary = {
        "period_start": payload["period_start"],
        "period_end": payload["period_end"],
        "source": payload["source"],
        "currency": str(payload["currency"]).upper(),
    }
    if args.dry_run:
        print(json.dumps({"status": "VALID", "dry_run": True, "period": summary}, sort_keys=True))
        return 0

    token = os.getenv("PAID_BETA_ADMIN_TOKEN", "")
    if not args.base_url.startswith("https://"):
        print(json.dumps({"status": "BLOCKED", "detail": "HTTPS base URL required"}))
        return 2
    if not token:
        print(json.dumps({"status": "BLOCKED", "detail": "PAID_BETA_ADMIN_TOKEN is required"}))
        return 2

    status, code = submit_payload(base_url=args.base_url, token=token, payload=payload)
    print(json.dumps({"status": status, "http_status": code, "period": summary}, sort_keys=True))
    return 0 if status in {"RECORDED", "ALREADY_RECORDED"} else 1


if __name__ == "__main__":
    sys.exit(main())
