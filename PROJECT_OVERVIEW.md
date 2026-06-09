# ZoL0 Current-State Technical Overview

ZoL0 is a KuCoin-only, PAPER-first trading research and validation codebase with an isolated paid-beta SaaS foundation.

## Current model

- Trading runtime: KuCoin only; PAPER by default; LIVE hard-gated.
- Paid beta: FastAPI, authentication, plans, Stripe billing, subscriptions, migrations, analytics, dashboard, CI, and Docker foundation.
- Bybit/pybit: deprecated and excluded.
- Profitability and LIVE readiness require fresh evidence; source code and historical LEVEL notes are not proof.

## Paid-beta security

Public registration always creates role `user`. First administrator creation uses a separate one-time bootstrap endpoint guarded by a minimum 32-character secret. Bootstrap is blocked after an administrator exists.

Paid reports, signal history, backtests, alerts, exports, and entitlement enforcement remain P0 before customer payments.

## Trading evidence

Core entrypoints:

- `scripts/controlled_kpi_run.py`
- `scripts/run_paper_readiness_gate.py`
- `scripts/profitability_audit_scorecard.py`
- `security/live_guard.py`

Operational readiness and profitability are separate gates. Profit promotion requires natural PAPER trades only, at least 60 closed trades per symbol/strategy/side cohort, positive full-cost expectancy, OOS profit factor at least 1.15, zero contaminated entries, and four consecutive positive weekly windows.

## Validation

```powershell
python -m pytest -q
Push-Location Alpha_Zol0-lvl_5-main
python scripts/run_paper_readiness_gate.py
pytest -q tests/test_paid_beta_security.py tests/test_paid_beta_contract.py tests/test_paid_beta_api.py
Pop-Location
```

See `PROFITABILITY_AND_REVENUE.md` for the revenue plan, unit economics, trading profit gate, and LIVE eligibility rules.
