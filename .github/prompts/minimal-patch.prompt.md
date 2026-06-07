# ONE_MINIMAL_PATCH

Use this prompt to implement one local, approved patch.

Steps:
1. Prove target first using repo-grounded evidence.
2. Patch only approved local scope.
3. Add or update targeted tests as needed.
4. Run `python -m py_compile <changed_python_files>`.
5. Run `pytest -q <targeted_tests>`.

Hard stop:
- Stop immediately if unapproved semantic mutation is required.
- Do not broaden scope or refactor outside the approved change.
