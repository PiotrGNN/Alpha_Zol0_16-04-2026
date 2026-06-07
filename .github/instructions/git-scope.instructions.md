---
applyTo: "**"
---

# Git Scope And Commit Discipline

Mandatory workflow:
- Capture a fresh dirty inventory before staging.
- Never use `git add .`.
- Stage only approved files with explicit paths.
- Verify exact staged scope before commit.
- Commit only after compile/test validation is complete.

Safety rules:
- Prefer named stash over blind delete/reset when temporary isolation is needed.
- Do not stage unrelated files.
- Stop if staged scope does not exactly match approved scope.
