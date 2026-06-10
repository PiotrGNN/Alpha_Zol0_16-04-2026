from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import zol0ctl


ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_command_registry_contains_expected_operations_and_no_live_path():
    expected = {
        "setup",
        "doctor",
        "up",
        "down",
        "restart",
        "status",
        "logs",
        "open",
        "test",
        "test-paid-beta",
        "test-full",
        "preflight",
        "rehearsal",
        "stripe-listen",
        "stripe-trigger",
        "backup",
        "restore-check",
        "economics-validate",
        "economics-import",
        "paper-start",
        "paper-status",
        "scorecard-build",
        "scorecard-check",
    }
    assert set(zol0ctl.COMMANDS) == expected
    assert not any("live" in name.lower() for name in zol0ctl.COMMANDS)
    assert "live" in zol0ctl.FORBIDDEN_COMMAND_FRAGMENTS


def test_redaction_removes_sensitive_values():
    payload = {
        "PAID_BETA_TOKEN_SECRET": "secret-value",
        "STRIPE_SECRET_KEY": "sk_test_secret",
        "nested": {"database_url": "postgresql://user:password@host/db"},
        "safe": "visible",
    }
    redacted = zol0ctl._redact(payload)
    rendered = json.dumps(redacted)
    assert "secret-value" not in rendered
    assert "sk_test_secret" not in rendered
    assert "password@host" not in rendered
    assert redacted["safe"] == "visible"


def test_parser_rejects_unknown_live_command():
    parser = zol0ctl.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["live-start"])


def test_compose_core_separates_migration_from_api_start():
    compose = _text("compose.yml")
    dockerfile = _text("Dockerfile.paid-beta")
    assert 'command: ["alembic", "upgrade", "head"]' in compose
    assert "service_completed_successfully" in compose
    assert 'command: ["uvicorn", "paid_beta.app:app"' in compose
    assert "alembic upgrade head && uvicorn" not in compose
    assert "alembic upgrade head && uvicorn" not in dockerfile


def test_api_and_postgres_have_no_public_port_mapping():
    core = _text("compose.yml")
    local = _text("compose.local.yml")
    staging = _text("compose.staging.yml")
    assert 'expose:\n      - "8000"' in core
    assert "8000:8000" not in core + local + staging
    assert "5432:5432" not in core + local + staging
    assert '"80:80"' in staging
    assert '"443:443"' in staging
    assert '"127.0.0.1:8080:8080"' in local


def test_staging_uses_secret_files_and_blocks_direct_secret_values():
    staging = _text("compose.staging.yml")
    config = _text("paid_beta/config.py")
    for marker in (
        "PAID_BETA_DATABASE_URL_FILE",
        "PAID_BETA_TOKEN_SECRET_FILE",
        "STRIPE_SECRET_KEY_FILE",
        "STRIPE_WEBHOOK_SECRET_FILE",
        "PAID_BETA_SMTP_PASSWORD_FILE",
    ):
        assert marker in staging
    assert "def _env_or_file" in config
    assert "unable to read secret file" in config
    assert "secret file for" in config


def test_caddy_routes_api_and_serves_spa_with_security_headers():
    caddy = _text("Caddyfile")
    assert "reverse_proxy @api api:8000" in caddy
    assert "root * /srv" in caddy
    assert "try_files {path} /index.html" in caddy
    assert 'X-Frame-Options "DENY"' in caddy
    assert "Content-Security-Policy" in caddy
    assert "/billing*" in caddy
    assert "/health" in caddy


def test_dashboard_is_same_origin_and_gateway_image_contains_built_assets():
    index = _text("dashboard/public/index.html")
    dockerfile = _text("Dockerfile.dashboard")
    assert "window.ZOLO_API_URL = '';" in index
    assert "FROM node:22-alpine AS build" in dockerfile
    assert "FROM caddy:" in dockerfile
    assert "COPY --from=build /app/dist /srv" in dockerfile


def test_local_placeholder_scorecard_is_never_profitability_or_live_evidence():
    payload = json.loads(_text("analysis/local-empty-scorecard.json"))
    assert payload["metadata"]["scope"]["exchange"] == "KuCoin"
    assert payload["metadata"]["scope"]["mode"] == "PAPER_ONLY"
    assert payload["metadata"]["scope"]["live_in_scope"] is False
    assert payload["profitability_ready"] is False
    assert payload["live_ready"] is False
    assert payload["blockers"]


def test_one_click_wrappers_delegate_only_to_control_plane():
    powershell = _text("zol0.ps1")
    shell = _text("zol0.sh")
    start = _text("START_ZOLO.cmd")
    stop = _text("STOP_ZOLO.cmd")
    assert "tools.zol0ctl" in powershell
    assert "tools.zol0ctl" in shell
    assert "zol0.ps1\" up local" in start
    assert "zol0.ps1\" down local" in stop
    assert "live" not in (powershell + shell + start + stop).lower()
