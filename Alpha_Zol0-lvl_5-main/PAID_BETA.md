# ZoL0 paid-beta foundation

Ta warstwa produktyzuje istniejące dane i wyniki PAPER jako usługę research/signals/backtest SaaS. Nie modyfikuje `BotCore`, strategii, progów, readiness ani egzekucji i nie wystawia publicznego live tradingu.

## Uruchomienie backendu

```bash
export PAID_BETA_TOKEN_SECRET='minimum-32-characters-secret-value'
export PAID_BETA_DATABASE_URL='sqlite:///./paid_beta.db'
pip install -r requirements-paid-beta.txt
alembic upgrade head
uvicorn paid_beta.app:app --reload
```

## Stripe

Wymagane zmienne: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_STARTER`, `STRIPE_PRICE_PRO`, `STRIPE_PRICE_REPORT`, `PAID_BETA_APP_URL`.

Endpointy:
- `POST /billing/checkout`
- `POST /billing/webhook`
- `POST /billing/portal`

Webhook zapisuje `provider_event_id`, dzięki czemu ponowne dostarczenie zdarzenia jest idempotentne.

## Frontend

```bash
cd dashboard
npm ci
npm run build
```

Dostępne ścieżki: `/pricing`, `/onboarding`, `/account/billing`, `/admin`.

## Ograniczenie zakresu

Repo pozostaje KuCoin-only i PAPER-first. Bybit/pybit nie zostały dodane. Publiczny live trading nie jest częścią płatnej bety.
