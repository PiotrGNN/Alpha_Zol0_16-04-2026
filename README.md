# ZoL0

ZoL0 is a KuCoin-only, PAPER-first trading research system with an isolated paid-beta SaaS product.

The source-of-truth Python project is `Alpha_Zol0-lvl_5-main/`.

## Current state

- Trading runtime: KuCoin only, PAPER by default, LIVE hard-gated.
- Paid beta: authentication, paid reports, signal history, backtests, alerts, exports, one-time artifacts, plan entitlements, Stripe billing, PostgreSQL migrations, audit logs, dashboard, monitoring and deployment tooling.
- Unified operation: Docker Compose, Caddy gateway and `tools.zol0ctl` wrappers.
- Profitability is not proven by repository code or synthetic tests.
- LIVE readiness requires fresh operational and profitability evidence plus explicit human approval.
- Bybit and pybit remain deprecated and excluded.

## Recommended local start

From `Alpha_Zol0-lvl_5-main/` on Windows:

```powershell
.\zol0.ps1 setup
.\zol0.ps1 doctor local
.\zol0.ps1 up local
.\zol0.ps1 open local
```

Or use `START_ZOLO.cmd`. Stop the stack with:

```powershell
.\zol0.ps1 down local
```

On Linux/macOS use the equivalent `./zol0.sh` commands.

The local stack exposes only the Caddy gateway on `127.0.0.1:8080`. FastAPI and PostgreSQL are not published directly.

## Main operational commands

```powershell
.\zol0.ps1 status local
.\zol0.ps1 logs local
.\zol0.ps1 test
.\zol0.ps1 test-paid-beta
.\zol0.ps1 rehearsal
.\zol0.ps1 preflight
.\zol0.ps1 economics-validate .\examples\economics-period.example.json
.\zol0.ps1 paper-start --minutes 5
.\zol0.ps1 paper-status
.\zol0.ps1 scorecard-check
```

There is no `live-start`, `promote-to-live`, or equivalent launcher command.

## Staging

Staging uses:

- Caddy on ports 80/443;
- same-origin dashboard and API;
- managed PostgreSQL;
- file-mounted Docker secrets;
- a read-only PAPER scorecard;
- separate Alembic migration before API start;
- redacted preflight and guarded restore rehearsal.

Real Stripe sandbox, SMTP delivery, domain/DNS, managed database backup/PITR and legal approval are external launch requirements.

## Documentation

- `PROJECT_OVERVIEW.md`: current technical state.
- `RUNBOOK.md`: launcher and validation commands.
- `PROFITABILITY_AND_REVENUE.md`: SaaS economics and trading profit gate.
- `Alpha_Zol0-lvl_5-main/PAID_BETA.md`: paid-beta deployment and security contract.
- `Alpha_Zol0-lvl_5-main/CLOSED_BETA_REHEARSAL.md`: staging rehearsal procedure.

## Core principles

- Evidence-first conclusions.
- Natural PAPER evidence only for trading profitability claims.
- Operational readiness, SaaS economics and trading profitability are separate gates.
- No automatic LIVE promotion.
- No guaranteed-return claims.
- No committed secrets or runtime databases.
