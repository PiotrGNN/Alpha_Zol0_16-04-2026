# ZoL0 Runbook

## Trading PAPER validation

```powershell
Push-Location Alpha_Zol0-lvl_5-main
python scripts/controlled_kpi_run.py --variant-only before --before-min 5
python scripts/run_paper_readiness_gate.py
Pop-Location
```

## Full tests

```powershell
python -m pytest -q
```

## Paid-beta validation

```powershell
Push-Location Alpha_Zol0-lvl_5-main
pip install -r requirements-paid-beta.txt
alembic upgrade head
pytest -q tests/test_paid_beta_security.py tests/test_paid_beta_contract.py tests/test_paid_beta_api.py
Push-Location dashboard
npm ci
npm run build
Pop-Location
Pop-Location
```

## Paid-beta administration

Public registration always creates a normal user. The first administrator must be provisioned through the separate one-time bootstrap flow documented in `Alpha_Zol0-lvl_5-main/PAID_BETA.md`. The bootstrap must remain fail-closed and unavailable after the first administrator exists.

## Readiness policy

Operational readiness and profitability are separate gates. No LIVE or profitability claim is valid without fresh artifacts. See `PROFITABILITY_AND_REVENUE.md`.

## Artifact policy

Do not commit runtime outputs, KPI results, local databases, model binaries, logs, coverage dumps, secrets, or temporary debug files.
