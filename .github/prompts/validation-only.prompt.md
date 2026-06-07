# VALIDATION_ONLY

Use this prompt to validate without changing code.

Constraints:
- No edits.
- No staging.
- No commit.

Validation steps:
1. Run `python -m py_compile <changed_python_files>`.
2. Run `pytest -q <targeted_tests>`.
3. If behavior changed, run PAPER-only runtime validation.

Reporting requirements:
- Provide exact command outputs.
- Provide exact artifact paths.
- Mark PASS/FAIL/CONTAMINATED explicitly.
