from __future__ import annotations

import hmac
from fastapi import Header, HTTPException, Request, status

from app.auth.identity import CSRF_COOKIE, SESSION_COOKIE, get_session_user
from app.auth.telegram import validate_init_data
from app.core.config import get_settings


async def require_operator(
    request: Request,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> dict:
    settings = get_settings()
    session_token = request.cookies.get(SESSION_COOKIE)
    if session_token:
        user = get_session_user(session_token)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Сессия недействительна или истекла.")
        if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            csrf_cookie = request.cookies.get(CSRF_COOKIE, "")
            if not csrf_cookie or not x_csrf_token or not hmac.compare_digest(csrf_cookie, x_csrf_token):
                raise HTTPException(status_code=403, detail="CSRF-проверка не пройдена.")
        if user.get("must_change_password"):
            raise HTTPException(status_code=403, detail="Сначала измени временный пароль.")
        roles = set(user.get("roles", []))
        if request.url.path.startswith("/api/v1/paper/risk-settings"):
            if user.get("trading_access") == "disabled" and request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
                raise HTTPException(status_code=403, detail="Торговый доступ отключён.")
            if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
                if not roles.intersection({"OWNER", "ADMIN"}):
                    raise HTTPException(status_code=403, detail="Недостаточно прав для изменения риск-настроек.")
        elif request.url.path.startswith("/api/v1/paper/") or request.url.path.startswith("/api/v1/ai/execute-signal"):
            if user.get("trading_access") == "disabled":
                raise HTTPException(status_code=403, detail="Торговый доступ отключён.")
            if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
                if user.get("trading_access") != "paper" or not roles.intersection({"OWNER", "ADMIN", "TRADER"}):
                    raise HTTPException(status_code=403, detail="У аккаунта нет разрешения создавать или изменять PAPER-ордера.")
        elif request.url.path.startswith("/api/v1/backtests/run") and request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            if not roles.intersection({"OWNER", "ADMIN", "TRADER"}):
                raise HTTPException(status_code=403, detail="Недостаточно прав для запуска бэктестов.")
        user["user_id"] = user["id"]
        user["username"] = user["login"]
        user["auth_mode"] = "session"
        return user
    if settings.dev_auth_enabled and settings.app_env == "development":
        return {"user_id": "local-dev", "id": "local-dev", "username": "local-dev", "login": "local-dev", "first_name": "Development operator", "auth_mode": "development", "role": "OWNER", "roles": ["OWNER"], "permissions": ["*"], "trading_access": "paper", "must_change_password": False}
    if not settings.telegram_bot_token or not x_telegram_init_data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется авторизация.")
    try:
        telegram_user = validate_init_data(x_telegram_init_data, settings.telegram_bot_token, settings.telegram_auth_max_age_seconds)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Недействительная или устаревшая авторизация Telegram.") from exc
    # A verified Telegram ID is not an application role. It must already be linked
    # from an authenticated application account; allowlists never grant OWNER.
    from app.auth.identity import connect, user_payload, iso
    with connect() as conn:
        linked = conn.execute("SELECT u.* FROM telegram_accounts t JOIN users u ON u.id=t.user_id WHERE t.telegram_user_id=?", (str(telegram_user["user_id"]),)).fetchone()
        if not linked or linked["status"] != "ACTIVE" or (linked["expires_at"] and linked["expires_at"] <= iso()):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Сначала войди по логину и паролю и привяжи Telegram к активному аккаунту.")
        app_user = user_payload(conn, linked)
    if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        raise HTTPException(status_code=401, detail="Для изменяющих запросов сначала обменяй Telegram initData на сессию приложения.")
    app_user["user_id"] = app_user["id"]
    app_user["username"] = app_user["login"]
    app_user["auth_mode"] = "telegram-linked-readonly"
    return app_user
