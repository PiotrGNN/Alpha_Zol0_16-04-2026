# DEVELOPMENT.md — Current developer guidance

## Authoritative status

ZoL0 is a KuCoin-only, PAPER-first trading research and validation system with an isolated paid-beta SaaS foundation.

Historical LEVEL and LEVEL-OMEGA documents describe prior ambitions and snapshots. They are not proof of current production readiness, complete coverage, trading profitability, or LIVE eligibility.

## Supported scope

- KuCoin market data and execution paths.
- PAPER-first runtime validation.
- Controlled KPI runs, readiness gates, telemetry, persistence, and profitability audits.
- Paid-beta authentication, plans, Stripe billing, subscriptions, migrations, analytics, dashboard, CI, and Docker foundation.
- Bybit/pybit are deprecated and must not be restored.

## Trading development rules

1. Keep `LIVE=0` for discovery and profitability validation.
2. Do not lower entry thresholds merely to increase trade count.
3. Separate operational readiness from profitability.
4. Accept only natural, uncontaminated PAPER trades into the profitability corpus.
5. Retain commit SHA, configuration fingerprint, data window, cost assumptions, and artifact hashes.
6. Add regression tests for runtime, gate, persistence, and evidence-contract changes.
7. Do not claim edge from code presence, simulated examples, or stale artifacts.

## Profitability contract

A promoted symbol/strategy/side cohort requires at least 60 natural closed trades, positive expectancy after fees/spread/slippage/funding, OOS profit factor at least 1.15, zero assisted/forced/mock/unknown entries, and four consecutive positive fresh weekly windows.

See `../PROFITABILITY_AND_REVENUE.md` for the complete governance contract.

## Paid-beta development rules

- Public registration always creates role `user`.
- First administrator provisioning is separate, secret-guarded, fail-closed, and one-time.
- Apply entitlement checks to every paid resource.
- Use managed PostgreSQL, Alembic deployment migrations, backups, and restore testing for production customer data.
- Validate Stripe replay, concurrency, cancellation, failed payment, refund, and one-time fulfillment paths.
- Do not expose public LIVE trading through the paid-beta product.

## Main validation commands

From the repository root:

```powershell
python -m pytest -q
```

From `Alpha_Zol0-lvl_5-main/`:

```powershell
python scripts/controlled_kpi_run.py --variant-only before --before-min 5
python scripts/run_paper_readiness_gate.py
pytest -q tests/test_paid_beta_security.py tests/test_paid_beta_contract.py tests/test_paid_beta_api.py
```

Dashboard:

```powershell
Push-Location dashboard
npm ci
npm run build
Pop-Location
```

## Documentation hierarchy

Current state is defined by:

- `../PROJECT_OVERVIEW.md`
- `../RUNBOOK.md`
- `../PROFITABILITY_AND_REVENUE.md`
- `README.md`
- `PAID_BETA.md`
- current CI/test output
- fresh runtime artifacts

Older TODO, LEVEL, AI, RL, federated-learning, market-making, arbitrage, coverage, and production-readiness statements are historical context unless re-proven by current code and evidence.
