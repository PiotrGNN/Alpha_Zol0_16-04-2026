---
applyTo: "core/**/*.py,strategies/**/*.py"
---

# Python Runtime And Strategy Guardrails

These paths are high risk. Any proposed change must be classified as exactly one of:
- telemetry-only
- bug fix
- runtime semantic mutation
- strategy mutation
- threshold/readiness mutation

Required behavior:
- If runtime semantic mutation, strategy mutation, or threshold/readiness mutation is required but not explicitly approved, stop and request approval.
- LIVE must remain untouched and hard-gated.
- Keep patches minimal and local.
- Do not add exchange fallbacks; KuCoin-only remains mandatory.

Validation requirements:
- Run `python -m py_compile <changed_python_files>`.
- Run targeted regression tests with `pytest -q <targeted_tests>`.
- If runtime behavior changed, run PAPER-only runtime validation and report artifact paths.
