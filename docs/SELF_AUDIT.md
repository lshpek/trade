# Self-audit — BOTVEX AI Trader

## Current verdict

**Expanded functional MVP; not production-ready.** This iteration adds a login/password identity system, Argon2id password hashing, interactive owner bootstrap, server-side opaque sessions, CSRF checks, basic RBAC, user management API/UI, one-time account activation/reset links, audit records, and Telegram identity linking/exchange. Existing SQLite PAPER simulation remains in place. The new frontend cannot be fully typechecked or built in this environment because the npm registry could not be resolved.

## Checks run

- `cd backend && python -m pytest -q` — **31 passed** on the latest source state.
- Earlier project baseline: Python syntax compilation and PAPER unit tests passed in the source archive; those are not substitutes for the final test run.
- `cd frontend && npm run typecheck` — **failed to complete meaningfully** because React, Vite and other packages are not installed in this working copy. The output reports missing modules and consequent JSX errors.
- `npm install --ignore-scripts --no-audit --no-fund --fetch-retries=0 --fetch-timeout=30000` — **BLOCKED** with `EAI_AGAIN` resolving `registry.npmjs.org`.
- Frontend production build — **not run successfully** because dependency installation was blocked.
- Docker build, Telegram WebView end-to-end test, and Railway deployment — **not run**.

## Security properties implemented

- No hardcoded owner password or live secrets.
- Argon2id password hashes; initial owner must rotate password before accessing protected product routes.
- Random session tokens are stored as hashes; session expiry, idle timeout and revocation are enforced server-side.
- CSRF token required for cookie-authenticated mutating routes.
- Disabled and expired accounts cannot use an existing session.
- Role and trading access are checked on the backend. VIEWER cannot submit PAPER orders; LIVE remains unavailable.
- Invitation tokens are hashed, one-time and expiring. Account and initial invitation records are created transactionally.
- Telegram signature/freshness are verified; Telegram identity alone never grants OWNER/ADMIN.

## Remaining blockers / risks

1. SQLite is still the persistence layer; PostgreSQL/Alembic migrations and production backup/restore validation remain incomplete.
2. Login rate limiting now uses atomic SQLite writes and is shared across workers that use the same identity database. For horizontally scaled deployments with separate database files, configure a shared database/rate limiter.
3. Frontend typecheck/build is unverified due npm DNS failure; source changes must be built on a machine with dependencies installed before deployment.
4. User activation and reset links require manual secure delivery; email delivery is not configured.
5. No dedicated session-management UI, self-service email recovery, external security audit, dependency scan, Docker build, production deployment, or Telegram client E2E has been completed.
6. LumiBot is not integrated. The public repository declares GPL-3.0; review license obligations before bundling or distributing it.
7. Gemini, real market data and historical backtesting remain unimplemented.
8. PAPER orders fill immediately at a user-entered reference price and do not model actual quotes, partial fills, slippage or unrealized drawdown.

A production-readiness claim is not justified by the current evidence.
