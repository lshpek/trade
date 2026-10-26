from __future__ import annotations

import secrets
import time
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.auth.identity import (
    CSRF_COOKIE, SESSION_COOKIE, activate_invitation, admin_update_user, assign_owner, audit_logs, iso,
    authenticate, change_password, create_session, create_user, get_session_user,
    consume_login_attempt, clear_login_attempts,
    get_user, issue_invitation, list_users, list_sessions, revoke_session_id, revoke_all_sessions, revoke_session, connect, user_payload,
)
from app.auth.sessions import require_operator
from app.auth.telegram import validate_init_data
from app.core.config import get_settings

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
admin = APIRouter(prefix="/api/v1/admin", tags=["user administration"])

class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeRequest(BaseModel):
    current_password: str | None = Field(default=None, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class InvitationActivationRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=12, max_length=256)


try:
    from pydantic import field_validator as _fv
    _PYD_V2 = True
except ImportError:
    _PYD_V2 = False


class CreateUserRequest(BaseModel):
    login: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$") if _PYD_V2 else Field(min_length=3, max_length=32, regex=r"^[A-Za-z0-9_.-]+$")
    role: str = "VIEWER"
    trading_access: str = "read"
    expiration: str = "never"


class UpdateUserRequest(BaseModel):
    role: str | None = None
    trading_access: str | None = None
    status: str | None = None
    expiration: str | None = None


class AssignOwnerRequest(BaseModel):
    confirm_login: str = Field(min_length=3, max_length=32)


def _check_login_rate_limit(key: str) -> None:
    if not consume_login_attempt(key, limit=10, window_seconds=300):
        raise HTTPException(status_code=429, detail="Слишком много попыток входа. Попробуй позже.")


def _clear_login_attempts(key: str) -> None:
    clear_login_attempts(key)


def _secure_cookie() -> bool:
    return get_settings().app_env.lower() not in {"development", "dev", "test"}


def _require_admin(actor: dict, permission: str = "users:create") -> None:
    roles = set(actor.get("roles", []))
    permissions = set(actor.get("permissions", []))
    if "OWNER" not in roles and permission not in permissions:
        raise HTTPException(status_code=403, detail="Недостаточно прав.")


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").strip()
    if forwarded:
        first_hop = forwarded.split(",")[0].strip()
        if first_hop:
            return first_hop[:80]
    return request.client.host if request.client else "unknown"


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict:
    ip = _client_ip(request)
    account_key = f"account:{ip}:{payload.login.strip().lower()}"
    ip_key = f"ip:{ip}"
    _check_login_rate_limit(account_key)
    _check_login_rate_limit(ip_key)
    user = authenticate(payload.login, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль.")
    _clear_login_attempts(account_key)
    token, csrf, expiry = create_session(user["id"], request.headers.get("user-agent"), ip)
    secure = _secure_cookie()
    response.set_cookie(SESSION_COOKIE, token, max_age=max(1, expiry - int(time.time())), httponly=True, secure=secure, samesite="lax", path="/")
    response.set_cookie(CSRF_COOKIE, csrf, max_age=max(1, expiry - int(time.time())), httponly=False, secure=secure, samesite="lax", path="/")
    return {"authenticated": True, "login": user["login"], "roles": user["roles"], "must_change_password": user["must_change_password"], "expires_at": expiry}


@router.post("/logout")
def logout(request: Request, response: Response, x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token")) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    csrf = request.cookies.get(CSRF_COOKIE, "")
    if token and (not csrf or not x_csrf_token or not secrets.compare_digest(csrf, x_csrf_token)):
        raise HTTPException(status_code=403, detail="CSRF-проверка не пройдена.")
    if token:
        revoke_session(token)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, secure=_secure_cookie(), samesite="lax")
    response.delete_cookie(CSRF_COOKIE, path="/", httponly=False, secure=_secure_cookie(), samesite="lax")
    return {"authenticated": False}


@router.get("/me")
def me(request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        user = get_session_user(token)
        if not user:
            raise HTTPException(status_code=401, detail="Сессия недействительна или истекла.")
        return {"authenticated": True, "user": user}
    settings = get_settings()
    if settings.dev_auth_enabled and settings.app_env == "development":
        return {"authenticated": True, "user": {"login": "local-dev", "roles": ["OWNER"], "permissions": ["*"], "must_change_password": False, "trading_access": "paper", "auth_mode": "development"}}
    return {"authenticated": False, "user": None}


@router.post("/change-password")
def change_password_route(payload: PasswordChangeRequest, request: Request, response: Response) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    csrf = request.cookies.get(CSRF_COOKIE, "")
    if not token:
        raise HTTPException(status_code=401, detail="Требуется авторизация.")
    header_csrf = request.headers.get("X-CSRF-Token", "")
    if not csrf or not header_csrf or not secrets.compare_digest(csrf, header_csrf):
        raise HTTPException(status_code=403, detail="CSRF-проверка не пройдена.")
    user = get_session_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Сессия недействительна или истекла.")
    try:
        change_password(user["id"], payload.new_password, payload.current_password, bootstrap_change=user["must_change_password"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Password change revokes all sessions. Clear current cookies and require fresh login.
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, secure=_secure_cookie(), samesite="lax")
    response.delete_cookie(CSRF_COOKIE, path="/", httponly=False, secure=_secure_cookie(), samesite="lax")
    return {"password_changed": True, "reauthentication_required": True}


@router.post("/activate")
def activate(payload: InvitationActivationRequest) -> dict:
    try:
        return {"activated": True, **activate_invitation(payload.token, payload.password)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reset-password")
def reset_password(payload: InvitationActivationRequest) -> dict:
    try:
        return {"password_reset": True, **activate_invitation(payload.token, payload.password)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sessions")
def current_sessions(request: Request) -> list[dict]:
    token = request.cookies.get(SESSION_COOKIE)
    user = get_session_user(token) if token else None
    if not user:
        raise HTTPException(status_code=401, detail="Требуется авторизация.")
    return list_sessions(user["id"])


@router.delete("/sessions/{session_id}")
def revoke_current_session(session_id: str, request: Request, response: Response) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    csrf = request.cookies.get(CSRF_COOKIE, "")
    header_csrf = request.headers.get("X-CSRF-Token", "")
    if not token:
        raise HTTPException(status_code=401, detail="Требуется авторизация.")
    if not csrf or not header_csrf or not secrets.compare_digest(csrf, header_csrf):
        raise HTTPException(status_code=403, detail="CSRF-проверка не пройдена.")
    user = get_session_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Сессия недействительна или истекла.")
    if not revoke_session_id(user["id"], session_id):
        raise HTTPException(status_code=404, detail="Сессия не найдена.")
    if user.get("session_id") == session_id:
        response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, secure=_secure_cookie(), samesite="lax")
        response.delete_cookie(CSRF_COOKIE, path="/", httponly=False, secure=_secure_cookie(), samesite="lax")
    return {"revoked": True}


@router.post("/telegram/exchange")
def telegram_exchange(request: Request, response: Response, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")) -> dict:
    settings = get_settings()
    if not settings.telegram_bot_token or not x_telegram_init_data:
        raise HTTPException(status_code=401, detail="Telegram initData недоступен.")
    try:
        tg = validate_init_data(x_telegram_init_data, settings.telegram_bot_token, settings.telegram_auth_max_age_seconds)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Недействительные данные Telegram.") from exc
    with connect() as conn:
        row = conn.execute("SELECT u.* FROM telegram_accounts t JOIN users u ON u.id=t.user_id WHERE t.telegram_user_id=?", (str(tg["user_id"]),)).fetchone()
        if not row or row["status"] != "ACTIVE" or (row["expires_at"] and row["expires_at"] <= iso()):
            raise HTTPException(status_code=403, detail="Telegram не привязан к активному аккаунту.")
        user = user_payload(conn, row)
    token, csrf, expiry = create_session(user["id"], request.headers.get("user-agent"), request.client.host if request.client else None)
    secure = _secure_cookie()
    response.set_cookie(SESSION_COOKIE, token, max_age=max(1, expiry - int(time.time())), httponly=True, secure=secure, samesite="lax", path="/")
    response.set_cookie(CSRF_COOKIE, csrf, max_age=max(1, expiry - int(time.time())), httponly=False, secure=secure, samesite="lax", path="/")
    return {"authenticated": True, "login": user["login"], "roles": user["roles"], "must_change_password": user["must_change_password"]}


@router.post("/telegram/link")
def link_telegram(request: Request, actor: dict = Depends(require_operator), x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")) -> dict:
    if actor.get("auth_mode") != "session":
        raise HTTPException(status_code=400, detail="Связать Telegram можно только из подтверждённой сессии приложения.")
    settings = get_settings()
    if not settings.telegram_bot_token or not x_telegram_init_data:
        raise HTTPException(status_code=400, detail="Telegram Mini App initData недоступен.")
    try:
        tg = validate_init_data(x_telegram_init_data, settings.telegram_bot_token, settings.telegram_auth_max_age_seconds)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Недействительные данные Telegram.") from exc
    from app.auth.identity import connect, iso, _audit
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT user_id FROM telegram_accounts WHERE telegram_user_id=?", (str(tg["user_id"]),)).fetchone()
        if existing and existing["user_id"] != actor["id"]:
            conn.rollback(); raise HTTPException(status_code=409, detail="Этот Telegram уже привязан к другому аккаунту.")
        conn.execute("INSERT INTO telegram_accounts(telegram_user_id,user_id,linked_at) VALUES(?,?,?) ON CONFLICT(telegram_user_id) DO UPDATE SET user_id=excluded.user_id,linked_at=excluded.linked_at", (str(tg["user_id"]), actor["id"], iso()))
        _audit(conn, actor["id"], actor["id"], "telegram.account_linked", metadata={"telegram_user_id": str(tg["user_id"])})
        conn.commit()
    return {"linked": True, "telegram_user_id": tg["user_id"]}


@admin.get("/users")
def users_list(limit: int = 50, offset: int = 0, search: str = "", actor: dict = Depends(require_operator)) -> dict:
    _require_admin(actor, "users:read")
    return list_users(limit, offset, search)


@admin.post("/users", status_code=201)
def users_create(payload: CreateUserRequest, actor: dict = Depends(require_operator)) -> dict:
    _require_admin(actor, "users:create")
    try:
        user = create_user(actor["id"], payload.login, payload.role, payload.trading_access, payload.expiration)
        return {"user": user, "activation_status": "NOT_DELIVERED", "activation_required": True, "message": "Аккаунт создан. Отдельно выпусти одноразовую ссылку активации; доставка email не настроена."}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409 if "существует" in str(exc) else 422, detail=str(exc)) from exc


@admin.get("/users/{user_id}")
def user_detail(user_id: str, actor: dict = Depends(require_operator)) -> dict:
    _require_admin(actor, "users:read")
    user = get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден.")
    return user


@admin.patch("/users/{user_id}")
def user_update(user_id: str, payload: UpdateUserRequest, actor: dict = Depends(require_operator)) -> dict:
    _require_admin(actor, "users:update")
    try:
        return admin_update_user(actor["id"], user_id, role=payload.role, trading_access=payload.trading_access, status=payload.status, expiration=payload.expiration)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@admin.post("/users/{user_id}/assign-owner")
def user_assign_owner(user_id: str, payload: AssignOwnerRequest, actor: dict = Depends(require_operator)) -> dict:
    if "OWNER" not in set(actor.get("roles", [])):
        raise HTTPException(status_code=403, detail="Только OWNER может назначить OWNER.")
    try:
        return assign_owner(actor["id"], user_id, payload.confirm_login)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@admin.post("/users/{user_id}/disable")
def user_disable(user_id: str, actor: dict = Depends(require_operator)) -> dict:
    _require_admin(actor, "users:disable")
    try:
        return admin_update_user(actor["id"], user_id, status="DISABLED")
    except (PermissionError, ValueError) as exc:
        raise HTTPException(status_code=403 if isinstance(exc, PermissionError) else 422, detail=str(exc)) from exc


@admin.post("/users/{user_id}/reactivate")
def user_reactivate(user_id: str, actor: dict = Depends(require_operator)) -> dict:
    _require_admin(actor, "users:update")
    try:
        return admin_update_user(actor["id"], user_id, status="ACTIVE")
    except (PermissionError, ValueError) as exc:
        raise HTTPException(status_code=403 if isinstance(exc, PermissionError) else 422, detail=str(exc)) from exc


@admin.post("/users/{user_id}/activation-link")
def user_activation_link(user_id: str, request: Request, actor: dict = Depends(require_operator)) -> dict:
    _require_admin(actor, "users:update")
    user = get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден.")
    try:
        token = issue_invitation(actor["id"], user_id, "activate")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"activation_url": str(request.base_url).rstrip("/") + "/activate#token=" + quote(token), "expires_in_seconds": 86400, "warning": "Одноразовая ссылка показана только сейчас. Не пересылай её через незащищённый канал."}


@admin.post("/users/{user_id}/reset-password")
def user_reset_link(user_id: str, request: Request, actor: dict = Depends(require_operator)) -> dict:
    _require_admin(actor, "users:update")
    if not get_user(user_id):
        raise HTTPException(status_code=404, detail="Пользователь не найден.")
    try:
        token = issue_invitation(actor["id"], user_id, "reset")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"reset_url": str(request.base_url).rstrip("/") + "/reset-password#token=" + quote(token), "expires_in_seconds": 86400, "warning": "Одноразовая ссылка показана только сейчас."}


@admin.post("/users/{user_id}/revoke-sessions")
def user_revoke_sessions(user_id: str, actor: dict = Depends(require_operator)) -> dict:
    _require_admin(actor, "users:update")
    target = get_user(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Пользователь не найден.")
    if "ADMIN" in set(actor.get("roles", [])) and target.get("role") in {"OWNER", "ADMIN"}:
        raise HTTPException(status_code=403, detail="ADMIN не может отзывать сессии OWNER/ADMIN.")
    revoke_all_sessions(user_id)
    return {"revoked": True}


@admin.get("/audit-logs")
def get_audit_logs(limit: int = 100, actor: dict = Depends(require_operator)) -> list[dict]:
    _require_admin(actor, "audit:read")
    return audit_logs(limit)
