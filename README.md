# ZoL0

ZoL0 is a KuCoin-only, PAPER-first trading research and validation system with an isolated paid-beta SaaS foundation.

The source-of-truth Python project is `Alpha_Zol0-lvl_5-main/`.

## Current state

- Trading runtime: KuCoin only, PAPER by default, LIVE hard-gated.
- Paid beta: authentication, plans, Stripe billing, subscriptions, migrations, analytics, dashboard, CI, and deployment foundation.
- Profitability is not proven by repository code alone.
- LIVE readiness requires fresh operational and profitability evidence.
- Bybit and pybit remain deprecated and excluded.

## Documentation

- `PROJECT_OVERVIEW.md`: current technical state.
- `PROFITABILITY_AND_REVENUE.md`: SaaS revenue plan and trading profit gate.
- `RUNBOOK.md`: validation and paid-beta commands.
- `Alpha_Zol0-lvl_5-main/PAID_BETA.md`: paid-beta deployment and security notes.

## Core principles

- Evidence-first conclusions.
- Natural PAPER evidence only for profitability claims.
- Operational readiness and profitability are separate gates.
- No automatic LIVE promotion.
- No guaranteed-return claims.

## Validation

```powershell
python -m py_compile Alpha_Zol0-lvl_5-main/core/BotCore.py
python -m pytest -q
```

Controlled PAPER run:

```powershell
Push-Location Alpha_Zol0-lvl_5-main
python scripts/controlled_kpi_run.py --variant-only before --before-min 5
Pop-Location
```

Do not commit secrets, runtime databases, logs, KPI outputs, generated reports, or local experiment artifacts.
