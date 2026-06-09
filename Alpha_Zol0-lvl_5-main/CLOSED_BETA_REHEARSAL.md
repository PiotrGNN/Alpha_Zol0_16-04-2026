# Paid-beta closed-beta deployment rehearsal

## Status and boundaries

This runbook validates the paid-beta SaaS product only. It does not enable public LIVE trading, modify BotCore, change strategies, lower thresholds or prove trading profitability.

Use Stripe **test mode**, a staging SMTP account, a managed PostgreSQL staging database, HTTPS and a secret manager. Never paste secret values into tickets, CI logs, shell history or repository files.

The legal approval flags must remain `0` until final documents have been completed for the operating entity and approved outside the code-review process.

## 1. Provision staging infrastructure

Prepare:

- HTTPS staging domain;
- managed PostgreSQL source database;
- separate empty disposable PostgreSQL restore database;
- Stripe test-mode account, webhook endpoint and three test price IDs;
- SMTP staging account;
- secret manager entries;
- read-only fresh KuCoin PAPER scorecard mount.

Copy `.env.closed-beta.example` into the secret-management workflow. Do not create a populated `.env` file in the repository.

**STOP** if any account, domain, database or secret is shared with production trading infrastructure.

## 2. Legal state

Review and complete the drafts under `paid_beta/legal/`.

Do not set these values to true until approval is complete:

- `PAID_BETA_TERMS_APPROVED`;
- `PAID_BETA_PRIVACY_APPROVED`;
- `PAID_BETA_REFUNDS_APPROVED`;
- `PAID_BETA_RISK_DISCLOSURE_APPROVED`.

For an infrastructure-only rehearsal, keep the flags false and do not start the production application lifecycle. Controlled CI may use isolated placeholder approvals solely to test the fail-closed startup contract.

## 3. Redacted structural preflight

Run without network access first:

```bash
python scripts/paid_beta_preflight.py --json-output preflight-structural.json
```

The report contains no secret values. It must show `PASS` before network validation.

Then run the external connectivity checks in the secured staging operator environment:

```bash
python scripts/paid_beta_preflight.py --network --json-output preflight-network.json
```

This validates:

- PostgreSQL connection and Alembic revision `0003_revenue_readiness_gate`;
- required tables;
- Stripe test-mode key and all price IDs;
- SMTP handshake, STARTTLS and optional authentication;
- HTTPS `/health` response;
- `public_live_trading=false`.

**STOP** on any `BLOCKED` result. Never replace `sk_test_` with a live key during rehearsal.

## 4. Application lifecycle rehearsal

The automated rehearsal covers:

1. signup;
2. login;
3. Pro checkout creation;
4. signed webhook processing;
5. Pro entitlement activation;
6. Pro artifact and alert access;
7. customer portal creation;
8. subscription cancellation;
9. Pro entitlement revocation;
10. one-time report checkout;
11. paid webhook and artifact-scoped access;
12. refund webhook;
13. artifact entitlement revocation.

Run:

```bash
pytest -q \
  tests/test_paid_beta_preflight.py \
  tests/test_paid_beta_economics_import.py \
  tests/test_paid_beta_closed_beta_rehearsal.py
```

This uses controlled fake Stripe services and a local test database. It performs no real charge and sends no real email.

After the automated test is green, repeat the same flow manually in Stripe test mode and record only Stripe object IDs, timestamps and pass/fail status. Do not record secret keys or full customer data.

## 5. Staging backup and restore rehearsal

Create a new empty disposable restore database. The script refuses to run when:

- source and restore URLs are identical;
- either URL is not PostgreSQL;
- the restore database contains any user tables;
- the source schema is not revision `0003_revenue_readiness_gate`.

Run from the secured operator shell:

```bash
export PAID_BETA_STAGING_REHEARSAL=1
bash scripts/paid_beta_staging_backup_restore_rehearsal.sh
```

The script:

- creates a temporary custom-format dump;
- restores it into the empty disposable database;
- compares Alembic revisions;
- compares row counts for critical paid-beta tables;
- removes the temporary dump on exit.

**STOP** if any row count differs. Do not point the restore URL at an existing environment.

## 6. Weekly economics import

Reconcile the weekly source data before import:

- Stripe gross receipts;
- Stripe fees;
- refunds;
- hosting and database costs;
- support cost and minutes;
- acquisition spend;
- active, new, churned and activated customers;
- checkout starts/completions;
- failed and recovered payments.

Copy `examples/economics-period.example.json`, replace every value and use a unique source such as `stripe-production-week-YYYY-WW`.

Validate locally:

```bash
python scripts/import_paid_beta_economics_period.py weekly-period.json --dry-run
```

Then set the short-lived administrator token only in the operator shell and import over HTTPS:

```bash
export PAID_BETA_ADMIN_TOKEN='from-secret-manager'
python scripts/import_paid_beta_economics_period.py weekly-period.json \
  --base-url https://beta.example.com
unset PAID_BETA_ADMIN_TOKEN
```

HTTP 409 is treated as `ALREADY_RECORDED`, making an exact retry safe. Any other non-success status is a failed import requiring investigation.

## 7. Closed-beta decision

Technical GO requires all of the following:

- all repository CI green;
- structural and network preflight PASS;
- Stripe test-mode manual lifecycle PASS;
- password-reset email received through staging SMTP;
- HTTPS health PASS with LIVE disabled;
- staging backup/restore PASS;
- legal documents approved;
- no secret-scanning findings;
- monitoring and operator ownership assigned.

Revenue readiness and trading profitability remain separate. Closed-beta technical GO does not authorize profitability claims, automatic LIVE promotion or real-money trading.

## 8. Evidence retention

Retain only redacted evidence:

- commit SHA and deployment version;
- CI run IDs;
- preflight PASS/BLOCKED output;
- Stripe test object IDs;
- webhook event IDs and timestamps;
- backup/restore timestamp and PASS result;
- weekly economics source ID;
- operator and reviewer names.

Never retain API keys, webhook secrets, database passwords, session tokens or customer passwords in the evidence bundle.
