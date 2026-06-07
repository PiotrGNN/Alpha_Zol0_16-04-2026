---
applyTo: "scripts/**/*.py,analysis/**/*.py"
---

# Scripts And Analysis Determinism Contract

Rules:
- Scripts must be deterministic and repo-grounded.
- Fail loudly on invalid or incomplete inputs.
- Emit explicit skip/reject reasons; do not silently continue.
- Maintain accepted/rejected run ledger outputs when producing analysis artifacts.
- Include data-quality metadata with each analysis result.

Boundaries:
- Do not mutate runtime behavior from analysis scripts.
- Do not relax scorecard/readiness criteria to force PASS.
- Stop on uncertainty instead of guessing.
