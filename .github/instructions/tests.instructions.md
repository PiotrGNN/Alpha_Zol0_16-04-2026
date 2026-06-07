---
applyTo: "tests/**/*.py"
---

# Test Scope Discipline

Rules for `tests/**/*.py`:
- Stay in test-only scope unless the user explicitly requests runtime code edits.
- Never perform silent runtime edits while changing tests.
- Keep changes minimal and targeted to the regression being validated.

Validation requirements:
- Run `python -m py_compile <changed_python_files>`.
- Run targeted `pytest -q <targeted_tests>`.

Git scope requirements:
- Staged scope must contain only intended test files unless explicitly approved.
- Never use `git add .`.
