# ZoL0 Nested Project

This directory contains the source-of-truth Python project for ZoL0.

For the full repo-grounded current-state description, see `../PROJECT_OVERVIEW.md`.

## Operating Constraints

- KuCoin-only.
- PAPER-first.
- LIVE is disabled by default and hard-gated.
- Runtime/profitability readiness must be established from fresh gate artifacts, not from historical LEVEL notes.
- No profitability, production-readiness, or LIVE-readiness claim is made by this README.

## Main Entrypoints

- Runtime loop: `core/BotCore.py`
- Controlled PAPER runner: `scripts/controlled_kpi_run.py`
- PAPER readiness gate: `scripts/run_paper_readiness_gate.py`
- Profitability/economics audit: `scripts/profitability_audit_scorecard.py`

## Run / Test

From the repository root:

```powershell
python -m py_compile Alpha_Zol0-lvl_5-main/core/BotCore.py
python -m pytest -q
```

Run a controlled PAPER command:

```powershell
Push-Location Alpha_Zol0-lvl_5-main
python scripts/controlled_kpi_run.py --variant-only before --before-min 5
Pop-Location
```
