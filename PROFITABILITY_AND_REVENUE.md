# ZoL0 — Profitability and Revenue Plan

**Status:** 2026-06-09  
**Scope:** KuCoin-only, PAPER-first trading research and paid-beta SaaS  
**Evidence rule:** no profitability or LIVE-readiness claim without fresh, reproducible artifacts.

## 1. Executive verdict

ZoL0 has two separate profitability paths:

1. **SaaS revenue — shortest path to cash flow.** Sell transparent PAPER research, reports, backtest evidence, signal history, alerts, and exports.
2. **Trading profitability — evidence-gated R&D.** Promote only natural strategy cohorts that remain profitable after fees, spread, slippage, funding, and adverse execution.

The paid-beta foundation provides authentication, roles, plans, Stripe billing, subscriptions, migrations, product analytics, dashboard routes, CI, and deployment assets. It is a monetization foundation, not yet a complete paid product.

The trading codebase does not by itself prove profitable economics. LIVE remains blocked until both the operational gate and the profit gate pass on fresh evidence.

## 2. Locked constraints

- KuCoin only.
- PAPER first; discovery and validation use `LIVE=0`.
- Bybit/pybit remain deprecated and must not be restored.
- No mock, seed, forced-open, fallback, assisted, or unknown trades in the accepted profitability corpus.
- Operational readiness and profitability are separate gates.
- No guaranteed-return, copy-trading, or “AI beats the market” claims.
- No automatic promotion to LIVE.

## 3. Founder-beta offer

| Product | Founder price | Required value |
|---|---:|---|
| Starter | 29 PLN/month | PAPER summaries, limited report history, basic watchlist |
| Pro | 79 PLN/month | Full history, alerts, provenance, exports, deeper analytics |
| One-time report | Configure before sale | Immutable report with costs, method, limitations, timestamp |

Founder pricing should be limited to the first 50 paying users or 90 days. Later pricing must be tested using measured conversion, retention, support cost, and contribution margin.

## 4. P0 before accepting payments

1. Add actual paid resources: authenticated reports, signal history, backtests, exports, alerts, and one-time report fulfillment.
2. Enforce plan/product entitlements on every paid endpoint.
3. Complete register, login, logout, password reset, session handling, and checkout-return UX.
4. Validate Stripe test-mode checkout, subscription changes, cancellations, failed payments, refunds, webhook replay, and concurrent delivery.
5. Use managed PostgreSQL in production; run Alembic during deployment; add encrypted backups and restore tests.
6. Add rate limiting, audit logs, input limits, secret rotation, dependency scanning, CSP, and isolated admin access.
7. Publish privacy/GDPR, terms, cancellation/refund policy, risk disclosure, and “research—not investment advice” language.
8. Add uptime, error, billing-webhook, backup, and incident monitoring.

## 5. Security baseline

- Public `/auth/register` always creates role `user`.
- First admin creation is separate from public onboarding.
- Admin bootstrap requires a minimum 32-character `PAID_BETA_ADMIN_BOOTSTRAP_SECRET`.
- Optional `PAID_BETA_BOOTSTRAP_ADMIN_EMAIL` constrains the authorized bootstrap address.
- Bootstrap becomes unavailable after the first admin is created.
- Bootstrap tokens and passwords must never be committed or logged.

## 6. Unit economics

Core formulas:

- `MRR = Starter users × 29 PLN + Pro users × 79 PLN`
- `Contribution margin = revenue − payment fees − variable hosting − variable support − refunds`
- `Break-even customers = fixed monthly cost / weighted contribution per customer`
- `CAC payback = CAC / monthly contribution per acquired customer`
- `LTV/CAC = lifetime contribution / CAC`

Do not scale paid acquisition until contribution margin is positive, CAC payback is at most three months, and measured LTV/CAC is at least 3.0.

### Planning scenarios

One-time reports below use a planning price of 199 PLN. These are scenarios, not forecasts.

| Scenario | Starter | Pro | Reports/month | Subscription MRR | Gross receipts |
|---|---:|---:|---:|---:|---:|
| Conservative | 30 | 10 | 5 | 1,660 PLN | 2,655 PLN |
| Base | 75 | 30 | 10 | 4,545 PLN | 6,535 PLN |
| Target | 150 | 75 | 20 | 10,275 PLN | 14,255 PLN |

## 7. Product profitability gate

Require four consecutive weeks of compliant measurements before scaling.

| KPI | Closed-beta gate | Scale gate |
|---|---:|---:|
| Checkout completion | >= 60% | >= 70% |
| Paid activation in 24h | >= 50% | >= 65% |
| Monthly logo churn | <= 10% | <= 5% |
| Refund rate | < 8% | < 4% |
| Gross margin | >= 65% | >= 75% |
| Payment recovery | >= 40% | >= 60% |
| Support/customer/month | <= 30 min | <= 15 min |
| CAC payback | Manual acquisition | <= 3 months |
| LTV/CAC | Sample-building | >= 3.0 |

Activation means consuming a real report, creating an alert/watchlist, or exporting evidence—not merely registering.

## 8. Trading evidence pipeline

### T0 — evidence hygiene

Every run must retain:

- commit SHA and configuration fingerprint;
- dataset and validation window;
- symbol, strategy, side, and regime metadata;
- fee, spread, slippage, and funding assumptions;
- artifact hashes and entry-truth classification.

Reject duplicates and any assisted, forced, seed, fallback, mock, or unknown lifecycle.

### T1 — natural PAPER corpus

- `LIVE=0`, `USE_MOCK=0`, KuCoin data only.
- Natural strategy entries only.
- Minimum **60 natural closed trades per symbol/strategy/side cohort**.
- Multiple sessions and at least two materially different market regimes.
- Do not lower entry thresholds only to manufacture trade count.

### T2 — cohort economics

Calculate for every cohort:

- net PnL and expectancy after all costs;
- profit factor, win rate, payoff ratio;
- drawdown and loss streak;
- fee, slippage, funding, and exit attribution;
- MFE/MAE, never-green, green-to-red;
- expected-net versus realized-net calibration;
- stability by time window and regime.

Quarantine cohorts with negative expectancy or profit factor below 1.0.

### T3 — out-of-sample validation

A candidate requires:

- positive in-sample and out-of-sample expectancy;
- OOS profit factor at least 1.15;
- no dependence on one outlier, session, or symbol;
- acceptable drawdown under the declared risk budget;
- full-cost and stressed-cost evaluation;
- replication on a fresh untouched window.

### T4 — PAPER shadow promotion

Freeze parameters before validation. Run without fallback or force-open. Require four consecutive positive weekly windows, zero critical runtime errors, zero corpus contamination, and acceptable expected-versus-realized drift.

### T5 — LIVE eligibility

LIVE remains blocked unless:

- operational readiness passes;
- the natural corpus is sufficient and clean;
- aggregate and OOS economics pass;
- kill switch, persistence, reconciliation, alerts, and rollback are validated;
- explicit human approval is recorded.

Any approved canary must use a strict capital-at-risk cap and a single cohort. A short winning streak cannot trigger automatic scaling.

## 9. Trading profit gate

| Metric | Requirement |
|---|---:|
| Natural closed trades | >= 60 per promoted cohort |
| Mock/forced/assisted trades | 0 |
| Unknown classifications | 0 |
| Net expectancy after full costs | > 0 |
| OOS profit factor | >= 1.15 |
| PF > 1 run rate | >= 70% |
| Profitable run rate | >= 70% |
| Positive selected cohorts | >= 75% |
| Never-green share | < 20% |
| Data/CSV/DB alignment | 100% pass |
| Critical runtime errors | 0 |
| Positive fresh weekly windows | >= 4 consecutive weeks |

These are governance thresholds, not guarantees of future returns.

## 10. Operational gate versus profit gate

### Operational gate

Proves that the system runs correctly: deterministic configuration, clean shutdown, persistence, reconciliation, telemetry, data integrity, kill switches, CI, and incident controls.

### Profit gate

Proves only that a clean natural cohort has positive full-cost economics with sufficient sample size, out-of-sample stability, and repeated fresh windows.

Passing one gate never implies passing the other.

## 11. Twelve-week execution plan

### Weeks 1–3 — product completion and staging

- Build paid report/history/backtest/alert delivery.
- Apply entitlement checks.
- Deploy PostgreSQL staging, migrations, backups, monitoring, and Stripe test mode.
- Complete authentication UX and legal pages.

### Weeks 4–5 — closed paid beta

- Recruit 10–20 narrow-profile users manually.
- Deliver one strong report format and one alert workflow.
- Target at least 10 real payments and 50% paid activation.

### Weeks 6–8 — retention and economics

- Improve the highest-retention workflow.
- Add lifecycle messaging and failed-payment recovery.
- Measure contribution margin, churn, refunds, support burden, and acquisition source.

### Weeks 9–12 — repeatable revenue and trading evidence

- Scale only channels with positive contribution margin.
- Continue natural PAPER collection independently of SaaS revenue.
- Promote no trading cohort until the complete profit gate passes.

## 12. Final rule

The fastest defensible route to revenue is a paid research and analytics product. Trading profitability remains an evidence-gated research objective. Product revenue must not be marketed as proof that the trading engine is profitable, and trading evidence must never bypass the operational or human-approval gates for LIVE.