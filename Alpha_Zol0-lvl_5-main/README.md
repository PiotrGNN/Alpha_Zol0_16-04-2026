# ZoL0 Nested Project

This directory contains the source-of-truth Python project for ZoL0.

## Operating constraints

- KuCoin only.
- PAPER first.
- LIVE disabled by default and hard-gated.
- Bybit/pybit deprecated and excluded.
- Profitability and LIVE readiness require fresh artifacts.
- Paid beta does not expose public LIVE trading.

## Main entrypoints

- Runtime: `core/BotCore.py`
- Controlled PAPER runner: `scripts/controlled_kpi_run.py`
- PAPER readiness gate: `scripts/run_paper_readiness_gate.py`
- Profitability audit: `scripts/profitability_audit_scorecard.py`
- Paid-beta API: `paid_beta/app.py`
- Paid-beta dashboard: `dashboard/`
- Unified control plane: `tools/zol0ctl.py`

## Recommended local start

Windows:

```powershell
.\zol0.ps1 setup
.\zol0.ps1 doctor local
.\zol0.ps1 up local
.\zol0.ps1 open local
```

Linux/macOS:

```bash
./zol0.sh setup
./zol0.sh doctor local
./zol0.sh up local
./zol0.sh open local
```

One-click Windows helpers:

```text
START_ZOLO.cmd
STOP_ZOLO.cmd
```

## Paid-beta state

The repository includes authentication, paid reports, signal history, backtests, alerts, exports, one-time artifacts, plan entitlements, Stripe billing, PostgreSQL migrations, audit logs, dashboard, monitoring, CI and Docker/Caddy deployment tooling.

Public registration always creates role `user`. First administrator creation uses a separate one-time bootstrap flow documented in `PAID_BETA.md`.

## Validation

```powershell
.\zol0.ps1 test
.\zol0.ps1 test-paid-beta
.\zol0.ps1 rehearsal
```

```powershell
python -m pytest -q
```

```powershell
python scripts/controlled_kpi_run.py --variant-only before --before-min 5
python scripts/run_paper_readiness_gate.py
```

See `../PROJECT_OVERVIEW.md`, `../RUNBOOK.md` and `../PROFITABILITY_AND_REVENUE.md` for the authoritative current state and profitability plan.
