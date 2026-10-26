# User management

## Initial owner

Run from `backend/`:

```powershell
python -m app.cli create-owner
```

Enter login `lshpek` (the CLI defaults to it) and a unique password of at least 12 characters. Input is hidden. The CLI will refuse to create an owner if any OWNER already exists or if the login is taken. The first successful login must rotate the bootstrap password before protected product routes are available. For local-shell recovery only, run `python -m app.cli reset-owner-password`, type `RESET OWNER`, and enter a new password twice. This revokes all owner sessions and requires password rotation at the next login.

To initialize the identity database without creating an account:

```powershell
python -m app.cli init-identity-db
```

## Create a user

In the Users screen, the initial form values are:

| Field | Default | Meaning |
|---|---|---|
| Login | `trader01` | Unique normalized login, 3–32 permitted ASCII characters |
| Role | `VIEWER` | Read-only application role |
| Trading access | `read` | PAPER writes are denied server-side |
| Expiration | `never` | `expires_at = NULL` |

The API endpoint is `POST /api/v1/admin/users`. Account creation returns `PENDING_ACTIVATION`, no password, and no invitation token. An activation invitation is recorded in the same database transaction. Because email delivery is not configured, an authorized admin separately calls `POST /api/v1/admin/users/{user_id}/activation-link` to generate a fresh one-time link. Deliver the link through a secure channel. The token is placed in the URL fragment (`#token=...`) and is not sent in the HTTP request path. It expires after 24 hours and is consumed once.

Activation is `POST /api/v1/auth/activate` with the invitation token and a password of at least 12 characters. Password reset follows the same one-time-token model using the admin reset-link endpoint.

## Roles and access

- `OWNER`: full administration; initial bootstrap only through the CLI.
- `ADMIN`: delegated user management and selected system controls. Cannot create another ADMIN, assign OWNER, modify OWNER/ADMIN accounts, or issue password reset/activation links for OWNER/ADMIN accounts.
- `TRADER`: read access plus PAPER order creation only when `trading_access=paper`.
- `VIEWER`: read-only. Cannot create or modify PAPER orders regardless of frontend behavior.

`trading_access` values are `read`, `paper`, and `disabled`. Access is checked on every protected request. LIVE trading is unavailable for every role.

## Endpoints

- `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, `GET /api/v1/auth/me`
- `POST /api/v1/auth/change-password`, `POST /api/v1/auth/activate`
- `POST /api/v1/auth/telegram/link`, `POST /api/v1/auth/telegram/exchange`
- `GET /api/v1/admin/users`, `POST /api/v1/admin/users`, `GET /api/v1/admin/users/{id}`, `PATCH /api/v1/admin/users/{id}`
- `POST /api/v1/admin/users/{id}/disable`, `/reactivate`, `/activation-link`, `/reset-password`, `/revoke-sessions`
- `POST /api/v1/admin/users/{id}/assign-owner` is a separate OWNER-only operation requiring explicit confirmation of the target login; ordinary create/update endpoints cannot assign OWNER.
- `GET /api/v1/admin/audit-logs`

Session inventory is persisted and server-side revocation is supported, but a dedicated per-session listing UI/endpoint is not yet complete.
