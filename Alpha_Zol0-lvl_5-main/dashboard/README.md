# ZoL0 paid-beta dashboard

Dependency-free frontend for the research/signals/backtest SaaS layer. It contains pricing, onboarding, billing and admin KPI routes. It does not expose public live trading.

```bash
npm ci
npm run build
```

Serve `dist/` and configure `window.ZOLO_API_URL` before loading `app.js` in production.
