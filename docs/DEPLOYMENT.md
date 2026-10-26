# Deployment notes

## Local setup

Use Python 3.11+ (the code was exercised in Python 3.13 in this environment). In one terminal:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item ..\.env.example .env
python -m app.cli init-identity-db
python -m app.cli create-owner
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
cd frontend
npm install
npm run typecheck
npm run build
npm run dev
```

`npm install` and the frontend checks must succeed before deployment. In the current execution environment, package installation was blocked by DNS failure for `registry.npmjs.org`; no successful frontend build is claimed.

## Railway / production

A Dockerfile and `railway.toml` are included as templates. No Railway account was accessed and no deployment was performed.

Before deploying:

1. Confirm frontend typecheck/build and Docker build on a network-enabled machine.
2. Configure `APP_ENV=production`, `DEV_AUTH_ENABLED=false`, `TELEGRAM_BOT_TOKEN`, and `BOTVEX_IDENTITY_DB_PATH` / `BOTVEX_DB_PATH` on persistent storage.
3. Use HTTPS. The session cookie is `Secure` outside development/test environments.
4. Back up both identity and PAPER SQLite databases. Do not run multiple replicas against the same local SQLite files.
5. Configure the Telegram Mini App URL to the deployed HTTPS origin. A user must sign in by application login/password and link Telegram before Telegram initData can exchange into an application session.
6. Do not set broker credentials or enable LIVE mode; broker integration and LIVE trading are not implemented.
7. Verify `/health`, `/ready`, login, forced password rotation, user creation/activation, CSRF rejection, account isolation and Telegram linking in the target environment.
8. Review current hosting plan, service count, memory and usage costs before enabling paid resources.

## Persistence warning

The PAPER store uses `BOTVEX_DB_PATH` (default `data/botvex_paper.sqlite3`). Identity uses `BOTVEX_IDENTITY_DB_PATH` (default `data/botvex_identity.sqlite3`). SQLite files on ephemeral hosting filesystems may disappear on replacement/redeploy. PostgreSQL/Alembic migration and backup/restore drills remain outstanding.

## Readiness semantics

`/health` reports process health. `/ready` intentionally reports `trading_ready=false`; it is not proof that trading integrations are available. Production readiness and deployment have not been verified.
