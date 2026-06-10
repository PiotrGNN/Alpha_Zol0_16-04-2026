# ZoL0 Runbook

## Official operating interface

Use the unified control plane from `Alpha_Zol0-lvl_5-main/`.

Windows:

```powershell
.\zol0.ps1 setup
.\zol0.ps1 doctor local
.\zol0.ps1 up local
.\zol0.ps1 open local
```

Linux/macOS:

```bash
./zol0.sh setup
./zol0.sh doctor local
./zol0.sh up local
./zol0.sh open local
```

One-click local startup is available through `START_ZOLO.cmd`; shutdown through `STOP_ZOLO.cmd`.

The launcher prints `PASS`, `BLOCKED` or `FAILED`. Optional evidence files are redacted.

## Local stack

The local Compose profile runs:

- Caddy gateway on `127.0.0.1:8080`;
- FastAPI on the internal Compose network;
- PostgreSQL on the internal Compose network;
- Mailpit for local SMTP capture;
- a fail-closed local placeholder scorecard.

FastAPI and PostgreSQL are not published directly.

Useful commands:

```powershell
.\zol0.ps1 status local
.\zol0.ps1 logs local
.\zol0.ps1 restart local
.\zol0.ps1 down local
```

## Validation

```powershell
.\zol0.ps1 test
.\zol0.ps1 test-paid-beta
.\zol0.ps1 rehearsal
.\zol0.ps1 preflight
```

Full repository validation remains:

```powershell
python -m pytest -q
```

Dashboard validation:

```powershell
Push-Location Alpha_Zol0-lvl_5-main\dashboard
npm ci
npm run build
Pop-Location
```

## Staging deployment rehearsal

Before staging deployment, verify external prerequisites:

- DNS and HTTPS domain;
- managed PostgreSQL;
- provider backup or PITR snapshot;
- separate empty disposable restore database;
- Stripe sandbox and webhook endpoint;
- SMTP staging account;
- legal approvals;
- file-mounted secrets;
- read-only PAPER scorecard.

Run:

```powershell
.\zol0.ps1 doctor staging
.\zol0.ps1 preflight --network
.\zol0.ps1 restore-check
.\zol0.ps1 post-deploy-smoke --base-url https://beta.example.com
```

The `backup` command is intentionally fail-closed unless the managed PostgreSQL provider backup is confirmed by environment flags. Repository tooling does not perform destructive provider-level backup operations.

## Weekly economics import

Validate first:

```powershell
.\zol0.ps1 economics-validate .\examples\economics-period.example.json
```

Import only over HTTPS with a short-lived admin token stored outside the repository:

```powershell
$env:PAID_BETA_ADMIN_TOKEN='from-secret-manager'
.\zol0.ps1 economics-import .\weekly-period.json --base-url https://beta.example.com
Remove-Item Env:\PAID_BETA_ADMIN_TOKEN
```

Exact duplicate imports are idempotent through the server-side uniqueness checks.

## PAPER research operations

```powershell
.\zol0.ps1 paper-start --minutes 5
.\zol0.ps1 paper-status
.\zol0.ps1 scorecard-build
.\zol0.ps1 scorecard-check
```

These commands keep `LIVE=0` and do not authorize trading profitability claims.

## Administration

Public registration always creates role `user`. The first administrator must be provisioned through the separate one-time bootstrap flow documented in `Alpha_Zol0-lvl_5-main/PAID_BETA.md`. The bootstrap must remain fail-closed and unavailable after the first administrator exists.

## Readiness policy

Operational readiness, SaaS revenue readiness and trading profitability are separate gates. No LIVE or profitability claim is valid without fresh artifacts and explicit human approval. There is no launcher command for LIVE promotion.

## Artifact policy

Do not commit runtime outputs, KPI results, local databases, model binaries, logs, coverage dumps, secrets or temporary debug files.
