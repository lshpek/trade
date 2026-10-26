import hashlib
import sqlite3
from urllib.parse import urlparse, parse_qs

import pytest
from fastapi.testclient import TestClient

from app.auth.identity import create_owner, get_user, normalize_login
from app.core.config import get_settings
from app.main import app


@pytest.fixture
def identity_env(monkeypatch, tmp_path):
    monkeypatch.setenv("BOTVEX_IDENTITY_DB_PATH", str(tmp_path / "identity.sqlite3"))
    monkeypatch.setenv("BOTVEX_DB_PATH", str(tmp_path / "paper.sqlite3"))
    monkeypatch.setenv("APP_ENV", "development")
    get_settings.cache_clear()
    settings = get_settings()
    settings.app_env = "development"
    settings.dev_auth_enabled = False
    settings.telegram_bot_token = ""
    yield tmp_path
    get_settings.cache_clear()


def test_bootstrap_owner_is_unique_and_hashes_password(identity_env):
    user_id = create_owner("lshpek", "correct horse battery staple")
    assert get_user(user_id)["must_change_password"] is True
    with sqlite3.connect(identity_env / "identity.sqlite3") as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id=?", (user_id,)).fetchone()
        assert row[0].startswith("$argon2id$")
        assert "correct horse battery staple" not in row[0]
    with pytest.raises(ValueError, match="OWNER уже существует"):
        create_owner("lshpek", "another safe password 123")


def test_login_rotation_create_viewer_and_activate_one_time(identity_env):
    owner_id = create_owner("lshpek", "correct horse battery staple")
    client = TestClient(app)
    response = client.post("/api/v1/auth/login", json={"login": "lshpek", "password": "correct horse battery staple"})
    assert response.status_code == 200
    assert response.json()["must_change_password"] is True
    csrf = client.cookies.get("botvex_csrf")
    assert csrf
    # The forced password rotation gates protected product routes.
    assert client.get("/api/v1/dashboard").status_code == 403
    changed = client.post("/api/v1/auth/change-password", headers={"X-CSRF-Token": csrf}, json={"new_password": "a different strong password 456"})
    assert changed.status_code == 200
    assert changed.json()["reauthentication_required"] is True
    assert client.get("/api/v1/dashboard").status_code == 401

    response = client.post("/api/v1/auth/login", json={"login": "LSHPEK", "password": "a different strong password 456"})
    assert response.status_code == 200
    csrf = client.cookies.get("botvex_csrf")
    created = client.post("/api/v1/admin/users", headers={"X-CSRF-Token": csrf}, json={"login": "trader01", "role": "VIEWER", "trading_access": "read", "expiration": "never"})
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["user"]["login"] == "trader01"
    assert payload["user"]["role"] == "VIEWER"
    assert payload["user"]["trading_access"] == "read"
    assert payload["user"]["expires_at"] is None
    assert payload["user"]["status"] == "PENDING_ACTIVATION"
    assert "token" not in created.text.lower()

    link = client.post(f"/api/v1/admin/users/{payload['user']['id']}/activation-link", headers={"X-CSRF-Token": csrf})
    assert link.status_code == 200, link.text
    token = parse_qs(urlparse(link.json()["activation_url"]).fragment)["token"][0]
    activation = client.post("/api/v1/auth/activate", json={"token": token, "password": "viewer password 123456"})
    assert activation.status_code == 200
    assert activation.json()["status"] == "ACTIVE"
    assert client.post("/api/v1/auth/activate", json={"token": token, "password": "viewer password 654321"}).status_code == 400


def test_viewer_cannot_create_paper_order(identity_env):
    create_owner("lshpek", "correct horse battery staple")
    client = TestClient(app)
    client.post("/api/v1/auth/login", json={"login": "lshpek", "password": "correct horse battery staple"})
    csrf = client.cookies.get("botvex_csrf")
    client.post("/api/v1/auth/change-password", headers={"X-CSRF-Token": csrf}, json={"new_password": "a different strong password 456"})
    client.post("/api/v1/auth/login", json={"login": "lshpek", "password": "a different strong password 456"})
    csrf = client.cookies.get("botvex_csrf")
    created = client.post("/api/v1/admin/users", headers={"X-CSRF-Token": csrf}, json={"login": "viewer01", "role": "VIEWER", "trading_access": "read", "expiration": "never"})
    assert created.status_code == 201
    user_id = created.json()["user"]["id"]
    link = client.post(f"/api/v1/admin/users/{user_id}/activation-link", headers={"X-CSRF-Token": csrf}).json()["activation_url"]
    token = parse_qs(urlparse(link).fragment)["token"][0]
    client.post("/api/v1/auth/activate", json={"token": token, "password": "viewer password 123456"})
    viewer = TestClient(app)
    logged = viewer.post("/api/v1/auth/login", json={"login": "viewer01", "password": "viewer password 123456"})
    assert logged.status_code == 200
    viewer_csrf = viewer.cookies.get("botvex_csrf")
    denied = viewer.post("/api/v1/paper/orders", headers={"X-CSRF-Token": viewer_csrf}, json={"symbol": "AAPL", "side": "BUY", "quantity": 1, "reference_price": 10, "idempotency_key": "viewer-key-123"})
    assert denied.status_code == 403


def test_login_generic_failure_and_csrf_required(identity_env):
    create_owner("lshpek", "correct horse battery staple")
    client = TestClient(app)
    assert client.post("/api/v1/auth/login", json={"login": "unknown", "password": "some wrong password"}).json()["detail"] == "Неверный логин или пароль."
    client.post("/api/v1/auth/login", json={"login": "lshpek", "password": "correct horse battery staple"})
    no_csrf = client.post("/api/v1/auth/change-password", json={"new_password": "a different strong password 456"})
    assert no_csrf.status_code == 403


def test_login_normalizes_login():
    assert normalize_login("  Trader01 ") == "trader01"
    with pytest.raises(ValueError):
        normalize_login("абв")


def test_last_owner_cannot_be_disabled(identity_env):
    from app.auth.identity import admin_update_user
    owner_id = create_owner("lshpek", "correct horse battery staple")
    with pytest.raises(ValueError, match="последнего активного OWNER"):
        admin_update_user(owner_id, owner_id, status="DISABLED")


def test_admin_cannot_create_admin_or_change_owner(identity_env):
    from app.auth.identity import create_user, admin_update_user
    owner_id = create_owner("lshpek", "correct horse battery staple")
    admin_user = create_user(owner_id, "admin01", "ADMIN", "read", "never")
    from app.auth.identity import PASSWORDS
    with sqlite3.connect(identity_env / "identity.sqlite3") as conn:
        conn.execute("UPDATE users SET status='ACTIVE',password_hash=? WHERE id=?", (PASSWORDS.hash("admin test password 123"), admin_user["id"]))
        conn.commit()
    with pytest.raises(PermissionError, match="ADMIN"):
        create_user(admin_user["id"], "admin02", "ADMIN", "read", "never")
    with pytest.raises(PermissionError, match="OWNER"):
        admin_update_user(admin_user["id"], owner_id, status="DISABLED")


def test_idle_expired_session_is_revoked(identity_env):
    import time
    from app.auth.identity import create_session, get_session_user
    owner_id = create_owner("lshpek", "correct horse battery staple")
    token, _, _ = create_session(owner_id)
    with sqlite3.connect(identity_env / "identity.sqlite3") as conn:
        conn.execute("UPDATE sessions SET last_seen_at=? WHERE token_hash=?", (int(time.time()) - 1900, hashlib.sha256(token.encode()).hexdigest()))
        conn.commit()
    assert get_session_user(token) is None
    with sqlite3.connect(identity_env / "identity.sqlite3") as conn:
        revoked = conn.execute("SELECT revoked_at FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()[0]
        assert revoked is not None


def _signed_telegram_data(token: str, user_id: int, auth_date: int) -> str:
    import hmac
    import json
    from urllib.parse import urlencode
    fields = {"auth_date": str(auth_date), "query_id": "AAE", "user": json.dumps({"id": user_id, "first_name": "Test"}, separators=(",", ":"))}
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    fields["hash"] = hmac.new(secret_key, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_telegram_link_and_exchange_uses_existing_app_role(identity_env):
    import time
    owner_id = create_owner("lshpek", "correct horse battery staple")
    settings = get_settings()
    settings.telegram_bot_token = "test-telegram-bot-token"
    client = TestClient(app)
    client.post("/api/v1/auth/login", json={"login": "lshpek", "password": "correct horse battery staple"})
    csrf = client.cookies.get("botvex_csrf")
    client.post("/api/v1/auth/change-password", headers={"X-CSRF-Token": csrf}, json={"new_password": "a different strong password 456"})
    client.post("/api/v1/auth/login", json={"login": "lshpek", "password": "a different strong password 456"})
    csrf = client.cookies.get("botvex_csrf")
    init_data = _signed_telegram_data(settings.telegram_bot_token, 987654321, int(time.time()))
    linked = client.post("/api/v1/auth/telegram/link", headers={"X-CSRF-Token": csrf, "X-Telegram-Init-Data": init_data})
    assert linked.status_code == 200, linked.text
    assert linked.json()["linked"] is True
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    exchanged = client.post("/api/v1/auth/telegram/exchange", headers={"X-Telegram-Init-Data": init_data})
    assert exchanged.status_code == 200, exchanged.text
    assert exchanged.json()["roles"] == ["OWNER"]
    dashboard = client.get("/api/v1/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["live_enabled"] is False


def test_local_owner_recovery_revokes_sessions_and_forces_rotation(identity_env):
    from app.auth.identity import create_session, get_session_user, reset_owner_password, authenticate
    owner_id = create_owner("lshpek", "correct horse battery staple")
    token, _, _ = create_session(owner_id)
    assert reset_owner_password("recovered owner password 123") == owner_id
    assert get_session_user(token) is None
    auth = authenticate("lshpek", "recovered owner password 123")
    assert auth and auth["must_change_password"] is True


def test_admin_cannot_issue_reset_link_for_owner(identity_env):
    from app.auth.identity import create_user, issue_invitation, PASSWORDS
    owner_id = create_owner("lshpek", "correct horse battery staple")
    admin_user = create_user(owner_id, "admin01", "ADMIN", "read", "never")
    with sqlite3.connect(identity_env / "identity.sqlite3") as conn:
        conn.execute("UPDATE users SET status='ACTIVE',password_hash=? WHERE id=?", (PASSWORDS.hash("admin test password 123"), admin_user["id"]))
        conn.commit()
    with pytest.raises(PermissionError, match="OWNER/ADMIN"):
        issue_invitation(admin_user["id"], owner_id, "reset")


def test_activation_invitation_cannot_be_issued_for_active_account(identity_env):
    from app.auth.identity import issue_invitation
    owner_id = create_owner("lshpek", "correct horse battery staple")
    with pytest.raises(ValueError, match="только для ожидающего"):
        issue_invitation(owner_id, owner_id, "activate")


def test_expired_account_revokes_existing_sessions(identity_env):
    from app.auth.identity import create_session, get_session_user
    owner_id = create_owner("lshpek", "correct horse battery staple")
    token, _, _ = create_session(owner_id)
    with sqlite3.connect(identity_env / "identity.sqlite3") as conn:
        conn.execute("UPDATE users SET expires_at=? WHERE id=?", ("2000-01-01T00:00:00+00:00", owner_id))
        conn.commit()
    assert get_session_user(token) is None
    with sqlite3.connect(identity_env / "identity.sqlite3") as conn:
        status_value = conn.execute("SELECT status FROM users WHERE id=?", (owner_id,)).fetchone()[0]
        revoked_at = conn.execute("SELECT revoked_at FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()[0]
    assert status_value == "EXPIRED"
    assert revoked_at is not None


def test_owner_assignment_requires_separate_confirmed_procedure(identity_env):
    from app.auth.identity import create_user, issue_invitation, activate_invitation, assign_owner, admin_update_user, create_session, get_session_user
    owner_id = create_owner("lshpek", "correct horse battery staple")
    target = create_user(owner_id, "promote01", "VIEWER", "read", "never")
    invitation = issue_invitation(owner_id, target["id"], "activate")
    activate_invitation(invitation, "target strong password 123")
    session_token, _, _ = create_session(target["id"])
    with pytest.raises(ValueError, match="отдельную защищённую процедуру"):
        admin_update_user(owner_id, target["id"], role="OWNER")
    with pytest.raises(ValueError, match="Подтверждение"):
        assign_owner(owner_id, target["id"], "wronglogin")
    promoted = assign_owner(owner_id, target["id"], "promote01")
    assert promoted["roles"] == ["OWNER"]
    assert get_session_user(session_token) is None
    with pytest.raises(ValueError, match="уже имеет роль OWNER"):
        assign_owner(owner_id, target["id"], "promote01")


def test_login_rate_limit_is_persisted_in_identity_database(identity_env):
    from app.auth.identity import consume_login_attempt, clear_login_attempts
    key = "127.0.0.1:trader01"
    clear_login_attempts(key)
    assert consume_login_attempt(key, limit=2, window_seconds=300) is True
    assert consume_login_attempt(key, limit=2, window_seconds=300) is True
    assert consume_login_attempt(key, limit=2, window_seconds=300) is False
    # The counter lives in SQLite, not a process-local dictionary.
    import sqlite3
    with sqlite3.connect(identity_env / "identity.sqlite3") as conn:
        assert conn.execute("SELECT COUNT(*) FROM login_attempts").fetchone()[0] == 2
    clear_login_attempts(key)
    assert consume_login_attempt(key, limit=2, window_seconds=300) is True
