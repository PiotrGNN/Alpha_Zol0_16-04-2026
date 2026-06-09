# ZoL0 paid-beta foundation

This layer packages existing PAPER research and analytics as a subscription/report SaaS. It does not change trading strategies, runtime thresholds, readiness semantics, execution, or LIVE controls.

## Current capabilities

- FastAPI health/status, registration, login, signed tokens, and roles.
- Starter, Pro, and one-time report product codes.
- Stripe Checkout, Customer Portal, subscriptions, and idempotent webhooks.
- SQLAlchemy models and Alembic migration.
- Funnel events, MRR summary, and admin KPI endpoints.
- Pricing, onboarding, billing, and admin dashboard routes.
- Dedicated Dockerfile and CI workflow.

This is a foundation. Paid report, signal-history, backtest, alert, export, entitlement, and fulfillment functionality remain P0 before accepting customer payments.

## Backend

```bash
export PAID_BETA_TOKEN_SECRET='minimum-32-character-value'
export PAID_BETA_DATABASE_URL='sqlite:///./paid_beta.db'
pip install -r requirements-paid-beta.txt
alembic upgrade head
uvicorn paid_beta.app:app --reload
```

SQLite is suitable for local development only. Use managed PostgreSQL, deployment migrations, backups, and restore tests for customer production data.

## Administrator bootstrap

Public `POST /auth/register` always creates role `user`.

The first administrator is created only through `POST /internal/bootstrap-admin`.

Required configuration:

- `PAID_BETA_ADMIN_BOOTSTRAP_SECRET`: at least 32 characters.
- `PAID_BETA_BOOTSTRAP_ADMIN_EMAIL`: optional authorized email restriction.

Required request header:

- `X-Admin-Bootstrap-Token`: must match the configured bootstrap secret.

The endpoint fails closed when the secret is absent or too short, rejects an invalid token, rejects an unauthorized email, and becomes unavailable after an administrator exists. Rotate or remove the bootstrap secret immediately after provisioning.

## Stripe

Required variables:

- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_PRICE_STARTER`
- `STRIPE_PRICE_PRO`
- `STRIPE_PRICE_REPORT`
- `PAID_BETA_APP_URL`

Endpoints:

- `POST /billing/checkout`
- `POST /billing/webhook`
- `POST /billing/portal`

Webhook events are deduplicated by provider event ID.

## Frontend

```bash
cd dashboard
npm ci
npm run build
```

Routes: `/pricing`, `/onboarding`, `/account/billing`, `/admin`.

## Validation

```bash
python -m py_compile paid_beta/*.py paid_beta/migrations/env.py paid_beta/migrations/versions/*.py
alembic upgrade head
pytest -q tests/test_paid_beta_security.py tests/test_paid_beta_contract.py tests/test_paid_beta_api.py
python -c "from paid_beta.app import app; assert app.title == 'ZoL0 Paid Beta API'"
```

## Commercial and safety boundaries

- Founder beta: Starter 29 PLN/month, Pro 79 PLN/month.
- Do not sell guaranteed returns, copy trading, or public LIVE execution.
- KuCoin-only and PAPER-first constraints remain unchanged.
- Bybit/pybit remain deprecated.
- See `../PROFITABILITY_AND_REVENUE.md` for P0, unit economics, product KPIs, and trading profit gates.
