# PR_SPLIT

Use this prompt to split commits into deterministic PR sets.

Classify each commit into one type:
- runtime surgical
- test-only
- scorecard/reporting
- artifact-only
- LIVE/readiness
- unsafe/mixed

Output requirements:
- Proposed PR order.
- Included commits per PR.
- Excluded commits per PR.
- Validation contract per PR.

Rules:
- Keep PRs single-purpose and minimal.
- Flag unsafe/mixed commits for rework before merge.
