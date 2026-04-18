# ZoL0

ZoL0 = KuCoin-only PAPER trading system.

The source-of-truth project directory is `Alpha_Zol0-lvl_5-main/`.

For the full repo-grounded current-state description, see `PROJECT_OVERVIEW.md`.

## Core Principles

- Deterministic execution and validation.
- Evidence-first conclusions from code, tests, logs, or runtime artifacts.
- Minimal patch scope for changes.
- No guessing when evidence is missing.

## Execution Modes

- `PAPER` is the default mode.
- `LIVE` is disabled by default and must remain gated.
- No live secrets, runtime databases, logs, KPI outputs, or experiment artifacts belong in git.

## Basic Run Command

From `Alpha_Zol0-lvl_5-main/`:

```powershell
python scripts/controlled_kpi_run.py
```

## Validation

From the repository root:

```powershell
python -m py_compile Alpha_Zol0-lvl_5-main/core/BotCore.py
python -m pytest -q
```

See `RUNBOOK.md` for the minimal PAPER runbook.
