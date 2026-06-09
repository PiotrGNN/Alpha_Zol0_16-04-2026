from __future__ import annotations

import argparse
import json
import os
import smtplib
import ssl
import sys
import urllib.request
from dataclasses import asdict, dataclass
from typing import Mapping

from sqlalchemy import create_engine, inspect, text

EXPECTED_SCHEMA_REVISION = "0003_revenue_readiness_gate"
REQUIRED_TABLES = {
    "alembic_version",
    "paid_beta_users",
    "paid_beta_artifacts",
    "paid_beta_artifact_grants",
    "paid_beta_audit_logs",
    "paid_beta_economics_periods",
}


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def _present(env: Mapping[str, str], name: str) -> bool:
    return bool((env.get(name) or "").strip())


def structural_checks(env: Mapping[str, str]) -> list[Check]:
    app_url = (env.get("PAID_BETA_APP_URL") or "").strip()
    database_url = (env.get("PAID_BETA_DATABASE_URL") or "").strip()
    stripe_key = (env.get("STRIPE_SECRET_KEY") or "").strip()
    webhook_secret = (env.get("STRIPE_WEBHOOK_SECRET") or "").strip()
    cors = (env.get("PAID_BETA_CORS_ORIGINS") or "").strip()

    checks = [
        Check("environment", env.get("PAID_BETA_ENV") == "production", "must equal production"),
        Check("database_driver", database_url.startswith(("postgresql://", "postgresql+")), "PostgreSQL required"),
        Check("https", app_url.startswith("https://"), "HTTPS application URL required"),
        Check("cors", bool(cors) and "localhost" not in cors and "127.0.0.1" not in cors, "non-localhost CORS required"),
        Check("token_secret", len(env.get("PAID_BETA_TOKEN_SECRET") or "") >= 32, "secret present and length >= 32"),
        Check("stripe_test_mode", stripe_key.startswith("sk_test_"), "test-mode Stripe key required for rehearsal"),
        Check("stripe_webhook", webhook_secret.startswith("whsec_"), "Stripe webhook signing secret required"),
        Check("stripe_starter_price", (env.get("STRIPE_PRICE_STARTER") or "").startswith("price_"), "Starter price ID required"),
        Check("stripe_pro_price", (env.get("STRIPE_PRICE_PRO") or "").startswith("price_"), "Pro price ID required"),
        Check("stripe_report_price", (env.get("STRIPE_PRICE_REPORT") or "").startswith("price_"), "report price ID required"),
        Check("smtp_host", _present(env, "PAID_BETA_SMTP_HOST"), "SMTP host required"),
        Check("smtp_from", "@" in (env.get("PAID_BETA_SMTP_FROM") or ""), "sender address required"),
        Check("password_reset_token_hidden", env.get("PAID_BETA_EXPOSE_PASSWORD_RESET_TOKEN", "0").lower() not in {"1", "true", "yes", "on"}, "reset token exposure forbidden"),
        Check("admin_bootstrap_disabled", env.get("PAID_BETA_ALLOW_ADMIN_BOOTSTRAP", "0").lower() not in {"1", "true", "yes", "on"}, "bootstrap must be disabled after provisioning"),
    ]
    for variable in (
        "PAID_BETA_TERMS_APPROVED",
        "PAID_BETA_PRIVACY_APPROVED",
        "PAID_BETA_REFUNDS_APPROVED",
        "PAID_BETA_RISK_DISCLOSURE_APPROVED",
    ):
        checks.append(
            Check(
                f"legal:{variable}",
                env.get(variable, "0").lower() in {"1", "true", "yes", "on"},
                "must be explicitly approved outside rehearsal code",
            )
        )
    return checks


def database_checks(database_url: str) -> list[Check]:
    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        tables = set(inspect(engine).get_table_names())
        missing = sorted(REQUIRED_TABLES - tables)
        return [
            Check("database_connectivity", True, "connection and SELECT 1 succeeded"),
            Check("database_schema_revision", version == EXPECTED_SCHEMA_REVISION, f"expected {EXPECTED_SCHEMA_REVISION}"),
            Check("database_required_tables", not missing, "all required tables present" if not missing else "missing: " + ", ".join(missing)),
        ]
    except Exception as exc:
        return [Check("database_connectivity", False, f"{type(exc).__name__}: connection or schema check failed")]


def stripe_checks(env: Mapping[str, str]) -> list[Check]:
    try:
        import stripe

        stripe.api_key = env["STRIPE_SECRET_KEY"]
        stripe.Balance.retrieve()
        for name in ("STRIPE_PRICE_STARTER", "STRIPE_PRICE_PRO", "STRIPE_PRICE_REPORT"):
            stripe.Price.retrieve(env[name])
        return [Check("stripe_api", True, "test-mode API and all price IDs resolved")]
    except Exception as exc:
        return [Check("stripe_api", False, f"{type(exc).__name__}: Stripe API validation failed")]


def smtp_checks(env: Mapping[str, str]) -> list[Check]:
    host = env["PAID_BETA_SMTP_HOST"]
    port = int(env.get("PAID_BETA_SMTP_PORT") or "587")
    try:
        with smtplib.SMTP(host, port, timeout=15) as client:
            client.ehlo()
            if env.get("PAID_BETA_SMTP_STARTTLS", "1").lower() in {"1", "true", "yes", "on"}:
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            if env.get("PAID_BETA_SMTP_USERNAME"):
                client.login(env["PAID_BETA_SMTP_USERNAME"], env.get("PAID_BETA_SMTP_PASSWORD", ""))
        return [Check("smtp_connectivity", True, "SMTP handshake/authentication succeeded")]
    except Exception as exc:
        return [Check("smtp_connectivity", False, f"{type(exc).__name__}: SMTP validation failed")]


def https_checks(app_url: str) -> list[Check]:
    try:
        request = urllib.request.Request(app_url.rstrip("/") + "/health", method="GET")
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        passed = response.status == 200 and payload.get("public_live_trading") is False
        return [Check("https_health", passed, "HTTPS health endpoint reachable and LIVE remains disabled")]
    except Exception as exc:
        return [Check("https_health", False, f"{type(exc).__name__}: HTTPS health validation failed")]


def main() -> int:
    parser = argparse.ArgumentParser(description="Redacted paid-beta closed-beta preflight")
    parser.add_argument("--network", action="store_true", help="validate Stripe, SMTP, PostgreSQL and HTTPS connectivity")
    parser.add_argument("--json-output", default="", help="optional output path; never contains secret values")
    args = parser.parse_args()

    checks = structural_checks(os.environ)
    if args.network:
        checks.extend(database_checks(os.environ.get("PAID_BETA_DATABASE_URL", "")))
        checks.extend(stripe_checks(os.environ))
        checks.extend(smtp_checks(os.environ))
        checks.extend(https_checks(os.environ.get("PAID_BETA_APP_URL", "")))

    report = {
        "status": "PASS" if all(item.passed for item in checks) else "BLOCKED",
        "network_checks_requested": bool(args.network),
        "checks": [asdict(item) for item in checks],
        "secrets_redacted": True,
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.json_output:
        with open(args.json_output, "w", encoding="utf-8") as handle:
            handle.write(rendered + "\n")
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
