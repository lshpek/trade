# Changelog

## 0.4.0-PRO — Quant & AI Signal Engine, Event-Driven Backtester, and Critical Bugfixes
- **Frontend Bugfix (`BUG-01`)**: Fixed missing `CircleHelp` and `Database` imports from `lucide-react` in `frontend/src/App.tsx` (which caused a `ReferenceError` crash on the Overview and Events tabs) and added the missing `users` key to `placeholderCopy` (`Record<Tab, string>`).
- **RBAC Bugfix (`BUG-02`)**: Fixed route precedence in `backend/app/auth/sessions.py` so `OWNER` and `ADMIN` accounts with `trading_access="read"` can configure PAPER risk limits (`PUT /api/v1/paper/risk-settings`) as specified by `risk:configure`.
- **Rate Limiter & Proxy Hardening (`BUG-03`)**: Stopped clearing the per-IP rate-limit counter (`ip_key`) upon successful login to prevent attackers with one valid account from resetting brute-force counters; added `X-Forwarded-For` client IP extraction and `--proxy-headers --forwarded-allow-ips='*'` in `Dockerfile`.
- **SQLite Transaction Atomicity (`BUG-04`)**: Wrapped multi-statement write blocks in `authenticate()`, `get_session_user()`, `revoke_session()`, `revoke_all_sessions()`, and `revoke_session_id()` with explicit `BEGIN IMMEDIATE` transactions.
- **PAPER Position Limit Hardening (`BUG-05`)**: Protected `max_position_notional` against artificially low `reference_price` on subsequent buys by checking `max(new_qty * reference_price, new_qty * new_avg)`, and normalized stored floats with `round(val, 8)`.
- **Quantitative Signal Engine (`quant_engine.py`)**: Added pure-Python multi-factor signal engine computing `EMA(9/21/50)`, `Wilder RSI(14)`, `MACD(12,26,9)`, `Wilder ATR(14)`, `ADX(14)`, `Bollinger Bands(20, 2.0)`, and `Rolling VWAP Z-Score(20)`, classifying market regimes (`TREND_BULL`, `TREND_BEAR`, `MEAN_REVERTING`, `HIGH_VOL_CHOP`) and sizing positions with `2.0x ATR` Stop-Loss and `4.2x ATR` Take-Profit (`R:R = 2.1`).
- **AI Advisor & 1-Click PAPER Execution (`ai_advisor.py`)**: Added `/api/v1/ai/signals` and `/api/v1/ai/execute-signal` supporting pre-trade Server-Side Risk Gate validation, 1-click single-order execution, and Auto-Pilot batch execution of top signals.
- **Historical Backtester (`backtester.py`)**: Added `/api/v1/backtests/run` and `/api/v1/backtests` with event-driven simulation across 3 strategies (`ensemble_quant`, `ema_trend_atr`, `vwap_zscore_reversion`), modeling fees (`fee_bps`), slippage (`slippage_bps`), intrabar SL/TP triggers, and computing `Sharpe`, `Sortino`, `Alpha`, `Profit Factor`, `Win Rate`, `Max Drawdown`, and SVG Equity curves.
- **Complete UI Wiring**: Replaced `ai`, `backtests`, and `events` placeholders in `App.tsx` with interactive panels; added active session management in `settings` and password-reset / `assign-owner` actions in `UserManagement.tsx`.

## 0.4.0-PRO — Quant & AI Signal Engine, Event-Driven Backtester, and Critical Bugfixes
- **Frontend Bugfix (`BUG-01`)**: Fixed missing `CircleHelp` and `Database` imports from `lucide-react` in `frontend/src/App.tsx` (which caused a `ReferenceError` crash on the Overview and Events tabs) and added the missing `users` key to `placeholderCopy` (`Record<Tab, string>`).
- **RBAC Bugfix (`BUG-02`)**: Fixed route precedence in `backend/app/auth/sessions.py` so `OWNER` and `ADMIN` accounts with `trading_access="read"` can configure PAPER risk limits (`PUT /api/v1/paper/risk-settings`) as specified by `risk:configure`.
- **Rate Limiter & Proxy Hardening (`BUG-03`)**: Stopped clearing the per-IP rate-limit counter (`ip_key`) upon successful login to prevent attackers with one valid account from resetting brute-force counters; added `X-Forwarded-For` client IP extraction and `--proxy-headers --forwarded-allow-ips='*'` in `Dockerfile`.
- **SQLite Transaction Atomicity (`BUG-04`)**: Wrapped multi-statement write blocks in `authenticate()`, `get_session_user()`, `revoke_session()`, `revoke_all_sessions()`, and `revoke_session_id()` with explicit `BEGIN IMMEDIATE` transactions.
- **PAPER Position Limit Hardening (`BUG-05`)**: Protected `max_position_notional` against artificially low `reference_price` on subsequent buys by checking `max(new_qty * reference_price, new_qty * new_avg)`, and normalized stored floats with `round(val, 8)`.
- **Quantitative Signal Engine (`quant_engine.py`)**: Added pure-Python multi-factor signal engine computing `EMA(9/21/50)`, `Wilder RSI(14)`, `MACD(12,26,9)`, `Wilder ATR(14)`, `ADX(14)`, `Bollinger Bands(20, 2.0)`, and `Rolling VWAP Z-Score(20)`, classifying market regimes (`TREND_BULL`, `TREND_BEAR`, `MEAN_REVERTING`, `HIGH_VOL_CHOP`) and sizing positions with `2.0x ATR` Stop-Loss and `4.2x ATR` Take-Profit (`R:R = 2.1`).
- **AI Advisor & 1-Click PAPER Execution (`ai_advisor.py`)**: Added `/api/v1/ai/signals` and `/api/v1/ai/execute-signal` supporting pre-trade Server-Side Risk Gate validation, 1-click single-order execution, and Auto-Pilot batch execution of top signals.
- **Historical Backtester (`backtester.py`)**: Added `/api/v1/backtests/run` and `/api/v1/backtests` with event-driven simulation across 3 strategies (`ensemble_quant`, `ema_trend_atr`, `vwap_zscore_reversion`), modeling fees (`fee_bps`), slippage (`slippage_bps`), intrabar SL/TP triggers, and computing `Sharpe`, `Sortino`, `Alpha`, `Profit Factor`, `Win Rate`, `Max Drawdown`, and SVG Equity curves.
- **Complete UI Wiring**: Replaced `ai`, `backtests`, and `events` placeholders in `App.tsx` with interactive panels; added active session management in `settings` and password-reset / `assign-owner` actions in `UserManagement.tsx`.

## 0.3.1 — auth hardening, retry-safe PAPER orders and interface polish
- Replaced the process-local login throttle with an atomic SQLite-backed counter, shared across app workers using the same identity database and retained across restarts. Attempts are keyed by hashed identifiers; limits apply per IP/login pair and per IP.
- Added a regression test for persisted login throttling; backend suite now reports 31 passed.
- Made PAPER order submission retry-safe in the UI: retrying the same payload reuses its idempotency key, preventing a duplicate fill if the first response is lost. Editing the payload generates a new key.
- Expired/invalid sessions now trigger a consistent return to login with a visible notice. API validation errors are displayed more clearly.
- Added quiet 30-second dashboard refresh and refreshes summary metrics after a PAPER order.
- Refined responsive visual hierarchy, cards, focus states, forms and mobile navigation.
- Verification: 31 backend tests passed, Python compile check passed, all six frontend TS/TSX files passed syntax transpilation. Full frontend typecheck/build remains blocked because dependencies are not cached and npm registry DNS failed earlier; no claim of a successful production build.
- Trading remains PAPER-only: no broker, exchange, or live market-data provider is connected. This release does not place real-money trades.

## 0.3.0 — identity, user management and security hardening
- Added Argon2id password hashing, interactive owner bootstrap (`python -m app.cli create-owner`), local-shell owner recovery (`reset-owner-password`) and mandatory password rotation after bootstrap/recovery.
- Added server-side opaque sessions, hashed session-token storage, absolute/idle expiry, logout/revocation, CSRF checks and session inspection/revocation endpoints.
- Added SQLite role/permission catalog, backend role checks, user management API and responsive user management screen.
- Added pending account creation, transactional hashed activation invitation, one-time activation/reset links and manual secure delivery workflow.
- Added audit records, disabled/expired-account handling, last-owner protection, separate explicit OWNER assignment, and admin privilege-escalation checks.
- Changed Telegram auth so verified Telegram identity must be linked to an existing app account; Telegram IDs no longer receive OWNER by allowlist.
- Added Telegram account link and signed-initData-to-session exchange endpoints.
- Preserved existing SQLite PAPER engine; added backend tests for identity bootstrap, login/password rotation, CSRF, activation single-use, VIEWER write denial, admin restrictions, last-owner protection and idle session expiry.
- Verification: 30 backend tests passed; Python compile check passed; frontend TS/TSX syntax transpilation passed. Frontend typecheck/build is blocked by npm registry DNS (`EAI_AGAIN`).
- Still not implemented: PostgreSQL/Alembic, email delivery, Gemini, LumiBot adapter, market data, historical backtesting, production deployment and Telegram WebView E2E.

## 0.2.0 — functional PAPER simulation slice
- Added SQLite-backed per-user virtual accounts, positions, simulated buy/sell orders, fee accounting and order history.
- Added idempotency keys and rejection when a key is reused with a different payload.
- Added server-side max order/position notional checks, daily realized-loss checks and kill switch.
- Connected Mini App Portfolio, Trades and Settings views to the PAPER API; added explicit simulation warnings and configurable risk controls.
- Added backend tests for PAPER accounting, safety controls, persistence, and idempotency.
- Verification at that point: 15 backend tests passed. Frontend build remained blocked by npm registry DNS failure.

## 0.1.0 — initial vertical slice
- Added FastAPI health/readiness and versioned dashboard/status/events endpoints.
- Added Telegram Mini App `initData` HMAC validation and explicit local-only development auth.
- Added a responsive React + TypeScript dashboard that displays integration availability honestly.
- Added Docker multi-stage build and Railway config as deployment starting points; not deployed or verified.
