# BOTVEX AI Trader — PAPER MVP

Mobile-first Telegram Mini App starter with a FastAPI backend. This version is **DEMO/PAPER-only**: it does not submit broker orders, does not claim to have a connected broker, and does not fabricate balances, positions, or PnL.

## Status

The current project contains a functional SQLite-backed PAPER simulation slice: per-user virtual accounts, simulated buy/sell orders, fees, positions, persistent order history, idempotency, server-side notional limits, daily realized-loss checks and a kill switch. The Mini App Portfolio, Trades and Settings screens are wired to these protected endpoints. This is still not a complete trading product: Gemini, LumiBot strategy execution, broker/live market data, real historical backtesting, PostgreSQL/Alembic, production Telegram end-to-end verification and Railway deployment are not implemented or verified.

## Requirements

- Python 3.11+
- Node.js 20+
- SQLite is used for the current PAPER simulation. The default database file is created under `backend/data/`; set `BOTVEX_DB_PATH` relative to the backend working directory to choose another location. For deployed use, SQLite needs a persistent mounted volume. PostgreSQL/Alembic migration is not implemented yet.

## Backend local run (PowerShell)

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item ..\.env.example .env
$env:DEV_AUTH_ENABLED = "true"
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Frontend local run (second terminal)

```powershell
cd frontend
npm install
npm run dev
```

Vite proxies `/api` and `/health` to `http://127.0.0.1:8000`.

## Tests and checks

```powershell
cd backend
python -m pip install -r requirements-dev.txt
pytest -q
python -m compileall app tests
```

```powershell
cd frontend
npm run typecheck
npm run build
```

## Environment variables

See `.env.example`. Never commit `.env`. `DEV_AUTH_ENABLED=true` is for local development only and must be false in deployment. Telegram auth requires `TELEGRAM_BOT_TOKEN` and verified Telegram Mini App `initData`.

## Login, users and Telegram linking

- Create the initial owner with `cd backend` then `python -m app.cli create-owner`. If local owner recovery is needed, use `python -m app.cli reset-owner-password` from the server shell; it requires explicit confirmation, revokes sessions and forces another password rotation. The password is entered interactively and is never embedded in source. Bootstrap refuses to overwrite an existing owner. The first login requires a password change.
- Identity records are stored separately in `BOTVEX_IDENTITY_DB_PATH` (default `data/botvex_identity.sqlite3`). The current identity store is SQLite; PostgreSQL/Alembic migration is not included in this build.
- Passwords are hashed with Argon2id. Browser sessions use random opaque tokens whose hashes are stored server-side; session and CSRF cookies are configured separately. Production requires HTTPS so the session cookie is Secure.
- User creation is available to authorized OWNER/ADMIN accounts under Users. Defaults are `trader01`, `VIEWER`, `read`, and `never`. Account creation leaves the user in `PENDING_ACTIVATION`; generate the one-time activation link separately and transmit it through a secure channel. The token is in the URL fragment, not the HTTP request path. Email delivery is not configured.
- Telegram `initData` is HMAC-verified using the bot token and its `auth_date` freshness is checked. Telegram identity alone does not grant OWNER/ADMIN. First sign in with an application account, then use **Привязать TG** inside Telegram. Later, the verified Telegram identity can be exchanged for an application session.
- `DEV_AUTH_ENABLED=true` works only when `APP_ENV=development`; do not enable it in a deployed environment.

For exact security caveats and incomplete integrations, see `docs/SECURITY.md`, `docs/USER_MANAGEMENT.md`, `docs/IMPLEMENTATION_MATRIX.md`, and `docs/SELF_AUDIT.md`.

## Railway

Deployment is **not confirmed** by this repository. Before deploying, create services and variables in your own Railway account. Do not enable paid resources without checking cost. This starter has `/health` and `/ready`; the current version does not yet include a production worker or broker connection.

## PAPER simulation API

Protected endpoints (require Telegram auth, or explicitly enabled local development auth):

- `GET /api/v1/paper/portfolio` — virtual cash and positions at simulation cost basis.
- `GET /api/v1/paper/orders` — simulated order history.
- `POST /api/v1/paper/orders` — simulated buy/sell at a user-supplied reference price; requires `symbol`, `side`, `quantity`, `reference_price`, and unique `idempotency_key`.
- `GET /api/v1/paper/risk-settings` / `PUT /api/v1/paper/risk-settings` — server-side order/position limits, daily realized-loss limit, and kill switch.

The API explicitly labels orders as simulated. It does not fetch prices or contact a broker. The daily-loss limit covers realized losses on sells, not unrealized drawdown.

## Safety

- PAPER/DEMO only; no real orders can be sent by this starter.
- No broker credentials or Gemini key belong in the frontend.
- A missing integration is shown as unavailable, not as connected.
- This is software infrastructure, not financial advice or a promise of returns. See `docs/IMPLEMENTATION_MATRIX.md` and `docs/SELF_AUDIT.md` for verified status and remaining blockers.
