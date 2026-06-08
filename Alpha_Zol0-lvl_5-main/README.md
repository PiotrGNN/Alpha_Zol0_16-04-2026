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

## Paid-beta state

The repository includes authentication, plans, Stripe billing, subscriptions, migrations, usage analytics, dashboard routes, CI, and Docker assets. Paid reports, signal history, backtests, alerts, exports, and entitlement delivery remain P0 before charging customers.

Public registration always creates role `user`. First administrator creation uses a separate one-time bootstrap flow documented in `PAID_BETA.md`.

## Validation

```powershell
python -m pytest -q
```

```powershell
python scripts/controlled_kpi_run.py --variant-only before --before-min 5
python scripts/run_paper_readiness_gate.py
```

```powershell
pip install -r requirements-paid-beta.txt
alembic upgrade head
pytest -q tests/test_paid_beta_security.py tests/test_paid_beta_contract.py tests/test_paid_beta_api.py
```

See `../PROJECT_OVERVIEW.md` and `../PROFITABILITY_AND_REVENUE.md` for the authoritative current state and profitability plan.
