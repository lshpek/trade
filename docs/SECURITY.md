# Security model and limitations

## Implemented in this MVP

- Passwords use Argon2id (`argon2-cffi`); plaintext passwords are not persisted.
- Initial owner bootstrap is an interactive CLI operation (`python -m app.cli create-owner`) and refuses to overwrite an existing owner. First login is gated until the owner changes the temporary password.
- Login responses use a generic invalid-credentials message. The rate limiter allows up to 10 attempts per five minutes per client-IP/login pair and per IP, persisted atomically in the SQLite `login_attempts` table across workers and restarts.
- Session cookies contain cryptographically random opaque tokens; only SHA-256 token hashes are stored. Session records have fixed expiry, idle expiry, revocation and user metadata.
- Session cookie is HttpOnly, SameSite=Lax and Secure outside development/test environments. Mutating cookie-authenticated routes require a CSRF token in `X-CSRF-Token` matching the CSRF cookie.
- Disabled/expired accounts and revoked/expired sessions are rejected server-side. Password changes revoke existing sessions.
- One-time activation/reset tokens are random, stored hashed, expire after 24 hours, and are consumed once. Generated links carry the token in the URL fragment so it is not sent in the HTTP request path. Creation of a pending account and its initial hashed invitation record is transactional.
- RBAC role/permission catalog tables and role-permission mappings are initialized idempotently. OWNER assignment is a separate OWNER-only endpoint with exact-login confirmation; ordinary create/update endpoints cannot assign OWNER. Authorization is enforced server-side; frontend hiding is only a usability layer.
- Telegram `initData` signature and freshness are verified. Telegram ID is not a role: it must be linked from an authenticated application account. Telegram-only writes require exchanging verified initData for an application session.
- PAPER trading remains simulation-only; no broker/live order adapter exists in this codebase.

## Important limitations

- The identity store is SQLite. PostgreSQL and Alembic migrations are not implemented. Back up the identity and PAPER databases before upgrades or moving hosts.
- Login rate limiting uses atomic SQLite writes (`login_attempts`) shared across workers using the same identity database. Successful login clears only the account-specific counter, never the per-IP counter.
- Activation/reset links are returned only by explicit owner/admin actions because no email delivery integration exists. Treat these links like credentials; they are only displayed in that response and should be sent over a secure channel.
- The account/permission catalog is a starter RBAC matrix, not a formal independent authorization service. Review permission codes before production use.
- No external penetration test, dependency vulnerability scan, production HTTPS check, Telegram WebView E2E test, or deployment verification has been completed.
- Password reset uses an admin-issued one-time link; self-service email recovery is not configured.
- Cookie security depends on correct production HTTPS and host configuration. Do not expose the application over plain HTTP in production.

## Operational rules

1. Set `APP_ENV=production`, `DEV_AUTH_ENABLED=false`, a valid `TELEGRAM_BOT_TOKEN` and an explicit allowed origin policy for the deployment.
2. Use HTTPS and protect backups of both SQLite databases.
3. Never commit `.env`, session cookies, invitation URLs, or bot/API credentials.
4. Keep LIVE trading disabled until separately designed, reviewed and tested; this project currently has no live trading implementation.
