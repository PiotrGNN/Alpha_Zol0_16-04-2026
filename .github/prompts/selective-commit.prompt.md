# SELECTIVE_COMMIT_ONLY

Use this prompt for commit-only execution.

Constraints:
- No `git add .`.
- Stage only approved files.

Required sequence:
1. Show dirty state (`git status --short`).
2. Stage exact approved files only.
3. Show `git diff --cached --stat`.
4. Show `git diff --cached --name-only`.
5. Show full cached diff.
6. Commit only if cached scope is exact.
7. Show post-commit scope (`git status --short`).

Hard stop:
- If any unrelated file appears in staged scope, unstage and stop.
