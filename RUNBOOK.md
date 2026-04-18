# ZoL0 Runbook

## PAPER Run

Run from the repository root:

```powershell
Push-Location Alpha_Zol0-lvl_5-main
python scripts/controlled_kpi_run.py --variant-only before --before-min 5
Pop-Location
```

## Tests

```powershell
python -m pytest -q
```

## Compile Check

```powershell
python -m py_compile Alpha_Zol0-lvl_5-main/core/BotCore.py
```

## Runtime Artifact Policy

Do not commit runtime outputs, experiment snapshots, KPI results, local databases, model binaries, logs, coverage dumps, local secrets, or temporary debug files.
