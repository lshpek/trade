# Implementation matrix — BOTVEX AI Trader

Status meanings: **VERIFIED** = directly exercised by a successful test/check; **IMPLEMENTED** = code exists but full acceptance verification remains; **PARTIAL** = a subset exists; **NOT_IMPLEMENTED** = absent; **BLOCKED** = environment or external access prevents verification.

| Requirement | Status | Evidence / limitation |
|---|---|---|
| FastAPI app, OpenAPI, health endpoint | VERIFIED | `backend/app/main.py`; existing API tests |
| Telegram Mini App initData HMAC and freshness | VERIFIED for unit cases | `backend/app/auth/telegram.py`; no real Telegram WebView E2E |
| Password login/logout/current user | VERIFIED for exercised API cases | `backend/app/api/identity_routes.py`; `backend/tests/test_identity.py` |
| Argon2id password hashing | VERIFIED for stored hash shape | `argon2-cffi`; bootstrap test verifies hash prefix and no plaintext |
| Secure owner bootstrap / first password rotation | VERIFIED for unit/API cases | `python -m app.cli create-owner` and `reset-owner-password`; duplicate bootstrap, recovery revocation and forced-rotation tests |
| Opaque server-side sessions, token hashing, revocation, expiry and idle timeout | IMPLEMENTED | `backend/app/auth/identity.py`; test coverage is not exhaustive for every expiry edge |
| CSRF for cookie-authenticated mutations | VERIFIED for missing-token case | `X-CSRF-Token` must match CSRF cookie; test rejects missing CSRF on password change |
| Login rate limiting | IMPLEMENTED | Atomic SQLite-backed 10 attempts/5 min per IP/login pair and per IP; shared by workers using the same identity DB and retained across restarts. A distributed Redis limiter is not configured |
| User creation form and real protected endpoint | IMPLEMENTED / API VERIFIED | UI defaults `trader01 / VIEWER / read / never`; endpoint and activation tests pass; frontend build blocked |
| One-time activation/reset tokens | VERIFIED for activation single-use case | Hashed token storage, 24-hour expiry, one-time consumption; no email delivery |
| RBAC role/permission catalog | IMPLEMENTED | SQLite `roles`, `permissions`, `role_permissions`, `user_roles`; code-level policy mapping remains authoritative |
| ADMIN cannot assign OWNER or edit OWNER/ADMIN | IMPLEMENTED | Backend checks; more adversarial tests recommended |
| VIEWER cannot create PAPER orders | VERIFIED | `test_viewer_cannot_create_paper_order` |
| User isolation in PAPER ledger | VERIFIED in existing tests | PAPER records keyed by authenticated account ID; Telegram multi-account E2E not run |
| Audit log for identity/security actions | IMPLEMENTED | `audit_logs`; endpoint protected by admin role; tamper-resistant external logging not implemented |
| Telegram account linking and session exchange | IMPLEMENTED | HMAC-verified initData; linked app account required; not tested inside Telegram client |
| SQLite PAPER buys/sells, fees, idempotency and risk limits | VERIFIED by existing tests | `backend/app/services/paper_trading.py`; simulation uses manually supplied prices |
| PAPER transaction and duplicate order handling | VERIFIED for covered cases | SQLite `BEGIN IMMEDIATE`, unique owner/idempotency key; no stress/concurrency test |
| LIVE trading disabled | VERIFIED for current scope | No broker/live order endpoint; health response says `live_enabled=false` |
| PostgreSQL + Alembic migrations | NOT_IMPLEMENTED | Identity and PAPER persistence use SQLite |
| Gemini API | NOT_IMPLEMENTED | No API client or AI output validation pipeline |
| LumiBot adapter | NOT_IMPLEMENTED | Repository/license researched; no dependency or adapter installed |
| Real market data | NOT_IMPLEMENTED | UI explicitly states unavailable |
| Historical backtesting | NOT_IMPLEMENTED | No historical data provider/engine wired |
| Frontend auth and user management UI | IMPLEMENTED, build BLOCKED | React source added; npm install failed with `EAI_AGAIN` resolving `registry.npmjs.org` |
| Frontend typecheck / production build | BLOCKED | Dependencies unavailable; neither check completed successfully |
| Backend tests | VERIFIED | Latest run: `31 passed` on the latest source state |
| Docker build | BLOCKED / NOT RUN | Docker build not run in this iteration |
| Railway deployment / Telegram WebView E2E | BLOCKED | No deployment credentials or external test environment |

## Evidence policy

Do not mark a requirement VERIFIED solely because source code exists. Run the relevant test, build, migration, or external verification and record the exact result.
