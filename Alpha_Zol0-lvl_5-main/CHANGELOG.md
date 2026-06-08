# CHANGELOG.md — ZoL0

## 2026-06-09

- Squash-merged PR #16: paid-beta SaaS foundation.
- Added FastAPI authentication, roles, plans, Stripe Checkout, subscriptions, idempotent webhooks, Alembic migration, usage analytics, dashboard routes, Docker assets, and dedicated CI.
- Hardened administrator provisioning: public registration always creates role `user`; first administrator uses a separate one-time, secret-guarded bootstrap flow.
- Fixed full Python CI integration for paid-beta dependencies and repository-independent contract-test paths.
- Verified green paid-beta backend/frontend CI, full Python test job, and LEVEL-OMEGA regression job before merge.
- Added the profitability and revenue plan separating SaaS revenue, operational readiness, trading profitability, and LIVE eligibility.
- KuCoin-only and PAPER-first constraints remain unchanged. Bybit/pybit remain deprecated.
- No profitability or LIVE-readiness claim is made without fresh evidence.

## 2026-04-20

- Recorded a historical PAPER readiness run and post-green protective-exit contract validation.
- The historical result remains useful as an artifact-specific observation only. It is not current proof of profitability or LIVE readiness.

## 2026-02-06

- Added KuCoin-only market-data and account-balance paths.
- Added health, market, balance, PAPER-state, and log endpoints.
- Enforced multi-step LIVE arming and PAPER-by-default behavior.

## Historical entries

Entries dated 2025-07 through 2025-08 describing production readiness, complete coverage, Bybit support, or LEVEL-OMEGA completion are retained only as historical project claims. They are not authoritative current-state evidence.

Current status is defined by `PROJECT_OVERVIEW.md`, `RUNBOOK.md`, `PAID_BETA.md`, `PROFITABILITY_AND_REVENUE.md`, current tests, and fresh runtime artifacts.
