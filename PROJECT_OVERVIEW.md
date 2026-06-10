# ZoL0 Current-State Technical Overview

ZoL0 is a KuCoin-only, PAPER-first trading research system with an isolated paid-beta SaaS product.

## Current model

- Trading runtime: KuCoin only; PAPER by default; LIVE hard-gated.
- Paid beta: FastAPI, authentication, paid reports, signal history, backtests, alerts, exports, one-time artifacts, entitlements, Stripe billing, PostgreSQL migrations, audit logs, dashboard and operational monitoring.
- Unified operation: `tools.zol0ctl`, PowerShell/POSIX wrappers, Docker Compose profiles and Caddy same-origin gateway.
- Bybit/pybit: deprecated and excluded.
- Profitability and LIVE readiness require fresh evidence; code presence, synthetic tests and historical LEVEL notes are not proof.

## Deployment architecture

The supported stack is:

1. Caddy gateway as the only public entrypoint.
2. Static dashboard and API on one origin.
3. FastAPI available only on the internal Compose network.
4. PostgreSQL available only on the internal network or as managed staging infrastructure.
5. A separate one-shot Alembic migration service that must complete before API startup.
6. Read-only PAPER scorecard mounting.
7. File-mounted staging secrets.

Local exposes only `127.0.0.1:8080`. Staging exposes only ports 80/443.

## Control plane

From `Alpha_Zol0-lvl_5-main/`:

```powershell
.\zol0.ps1 setup
.\zol0.ps1 doctor local
.\zol0.ps1 up local
.\zol0.ps1 status local
.\zol0.ps1 logs local
.\zol0.ps1 down local
```

The same Python implementation is available as:

```bash
python -m tools.zol0ctl <command>
```

There is no launcher command for LIVE, real-money promotion or automatic profitability promotion.

## Paid-beta security

Public registration always creates role `user`. First-administrator provisioning is separate, one-time, secret-guarded and fail-closed.

Paid reports, signal history, backtests, alerts, exports and one-time artifacts are protected by plan/product entitlements. Cancellation, failed payment and refund paths revoke access.

Production requires managed PostgreSQL, HTTPS, Stripe configuration, SMTP, secret files, legal approvals and a fresh read-only scorecard. Missing prerequisites block startup or preflight.

## Operational monitoring

The operational status check detects:

- missing or stale weekly economics data;
- unprocessed webhook events;
- failed-payment subscriptions;
- missing or stale trading scorecard;
- failed HTTPS health checks.

Operational status never authorizes profitability claims or LIVE.

## Trading evidence

Core entrypoints:

- `scripts/controlled_kpi_run.py`
- `scripts/run_paper_readiness_gate.py`
- `scripts/profitability_audit_scorecard.py`
- `security/live_guard.py`

Trading promotion requires natural PAPER trades only, at least 60 closed trades per symbol/strategy/side cohort, positive full-cost expectancy, OOS profit factor at least 1.15, zero contaminated entries and four consecutive positive weekly windows.

Operational readiness, SaaS revenue readiness and trading profitability remain independent gates.
