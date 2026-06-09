# ZoL0 — Profitability and Revenue Plan

**Status:** 2026-06-09  
**Scope:** KuCoin-only, PAPER-first trading research and paid-beta SaaS.

## Executive verdict

ZoL0 has two separate profitability paths:

1. **SaaS revenue:** the shortest path to cash flow through paid PAPER research, reports, signal history, alerts, backtests, and exports.
2. **Trading profitability:** an evidence-gated R&D path based only on natural PAPER trades and full-cost economics.

The paid-beta foundation is merged, but it is not yet a complete paid product. Trading profitability and LIVE readiness are not proven.

## Locked constraints

- KuCoin only.
- PAPER first.
- Bybit/pybit remain deprecated.
- No mock, seed, forced-open, fallback, assisted, or unknown trades in the accepted corpus.
- Operational readiness and profitability are separate gates.
- No guaranteed-return claims.
- No automatic LIVE promotion.

## Founder beta

| Product | Price | Required value |
|---|---:|---|
| Starter | 29 PLN/month | PAPER summaries, limited history, watchlist |
| Pro | 79 PLN/month | Full history, alerts, provenance, exports |
| One-time report | Configure before sale | Immutable report with method, costs, limits, timestamp |

Founder prices should be limited to the first 50 paying users or 90 days.

## P0 before accepting payments

1. Add authenticated paid reports, signal history, backtests, exports, alerts, and one-time report fulfillment.
2. Enforce plan and product entitlements.
3. Complete register, login, logout, password reset, session, and checkout-return UX.
4. Validate Stripe test-mode checkout, subscription changes, failed payments, cancellation, refunds, replay, and concurrency.
5. Use managed PostgreSQL, deployment migrations, backups, and restore tests.
6. Add rate limiting, audit logs, secret rotation, dependency scanning, CSP, and isolated admin access.
7. Publish privacy/GDPR, terms, cancellation/refund policy, risk disclosure, and research-only language.
8. Add uptime, error, webhook, backup, and incident monitoring.

## Unit economics

- `MRR = Starter users × 29 PLN + Pro users × 79 PLN`
- `Contribution margin = revenue − payment fees − variable hosting − support − refunds`
- `Break-even customers = fixed cost / weighted contribution per customer`
- `CAC payback = CAC / monthly contribution per acquired customer`
- `LTV/CAC = lifetime contribution / CAC`

Do not scale paid acquisition until contribution margin is positive, CAC payback is at most three months, and measured LTV/CAC is at least 3.0.

## Product profitability gate

Require four consecutive compliant weeks before scaling.

| KPI | Closed beta | Scale |
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

Activation means consuming a real report, creating an alert/watchlist, or exporting evidence.

## Trading evidence pipeline

### Evidence hygiene

Every run must retain commit SHA, configuration fingerprint, data window, symbol/strategy/side, fee/slippage/funding assumptions, artifact hashes, and entry-truth classification.

Reject duplicates and any assisted, forced, seed, fallback, mock, or unknown lifecycle.

### Natural PAPER corpus

- `LIVE=0`, `USE_MOCK=0`.
- KuCoin data only.
- Natural entries only.
- Minimum 60 natural closed trades per symbol/strategy/side cohort.
- Multiple sessions and at least two different market regimes.
- Do not lower thresholds only to manufacture trade count.

### Cohort economics

Calculate net PnL, expectancy, profit factor, win rate, payoff ratio, drawdown, fee/slippage/funding attribution, MFE/MAE, never-green share, green-to-red share, calibration error, and time/regime stability.

Quarantine cohorts with negative expectancy or profit factor below 1.0.

### Out-of-sample validation

A candidate requires positive in-sample and out-of-sample expectancy, OOS profit factor at least 1.15, acceptable drawdown, full-cost stress testing, no single-outlier dependence, and replication on a fresh untouched window.

### PAPER shadow promotion

Freeze parameters before validation. Run without fallback or force-open. Require four consecutive positive weekly windows, zero critical runtime errors, zero contamination, and acceptable expected-versus-realized drift.

### LIVE eligibility

LIVE remains blocked unless operational readiness passes, the natural corpus is sufficient and clean, OOS economics pass, kill switch/persistence/reconciliation/alerts/rollback are validated, and explicit human approval is recorded.

## Trading profit gate

| Metric | Requirement |
|---|---:|
| Natural closed trades | >= 60 per cohort |
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
| Positive weekly windows | >= 4 consecutive weeks |

These are governance thresholds, not guarantees.

## Operational gate versus profit gate

The operational gate proves correct execution, persistence, reconciliation, telemetry, data integrity, kill switches, CI, and rollback.

The profit gate proves only that a clean natural cohort has positive full-cost economics with sufficient sample size and out-of-sample stability.

Passing one gate never implies passing the other.

## Twelve-week plan

### Weeks 1–3

Complete paid value delivery, entitlement checks, PostgreSQL staging, migrations, backups, monitoring, Stripe test mode, authentication UX, and legal pages.

### Weeks 4–5

Run a closed beta with 10–20 narrow-profile users. Target at least 10 real payments and 50% paid activation.

### Weeks 6–8

Improve the highest-retention workflow. Measure contribution margin, churn, refunds, support burden, and acquisition source.

### Weeks 9–12

Scale only channels with positive contribution margin. Continue natural PAPER collection independently. Promote no trading cohort until the full profit gate passes.

## Final rule

The fastest defensible route to revenue is a paid research and analytics product. Product revenue is not proof of trading edge, and trading evidence cannot bypass operational or human-approval gates for LIVE.
