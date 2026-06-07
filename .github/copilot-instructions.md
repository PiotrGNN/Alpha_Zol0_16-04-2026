# ZoL0 Copilot Operating Contract

ZoL0 identity:
- KuCoin-first trading system.
- PAPER-first execution policy.
- LIVE is hard-gated and disabled by default.

Non-negotiable boundaries:
- KuCoin only.
- No Binance, Bybit, OKX, or CCXT fallback paths.
- No invented repository state.
- No broad refactor.
- No unapproved threshold/readiness/execution mutation.
- Do not touch LIVE unless explicitly approved.

Default workflow:
1. AUDIT_ONLY
2. PATCH_PLAN_ONLY
3. ONE_MINIMAL_PATCH
4. VALIDATION_ONLY
5. SELECTIVE_COMMIT_ONLY

Validation contract:
- `python -m py_compile <changed_python_files>`
- `pytest -q <targeted_tests>`
- If behavior changed: run PAPER-only runtime validation command and capture artifacts.

Git discipline:
- Never use `git add .`.
- Always inspect staged scope before commit.
- Stage only approved files.
- Stop on uncertainty instead of guessing.

Evidence and quality rules:
- All analysis must be repo-grounded and evidence-first.
- Every patch must be minimal, local, testable, and explicitly validated.
- Never claim profitability without clean runtime proof.
- Observed PnL is not the same as clean profitability proof.
- Reject contaminated corpus instead of forcing PASS.
- Separate audit, patch, validation, and commit phases.
