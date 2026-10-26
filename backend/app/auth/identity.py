"""Local identity/session service for BOTVEX AI Trader.

Identity persistence is intentionally isolated from the existing PAPER ledger. SQLite is
supported for this MVP; production PostgreSQL/Alembic migration is not claimed here.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
except ImportError:
    import ctypes

    class VerifyMismatchError(Exception):
        pass

    class VerificationError(Exception):
        pass

    class InvalidHashError(Exception):
        pass

    class _LibArgon2Hasher:
        """Native ctypes binding to system libargon2.so.1 when argon2-cffi wheel is absent."""
        def __init__(self, time_cost: int = 3, memory_cost: int = 65536, parallelism: int = 2) -> None:
            self.time_cost = time_cost
            self.memory_cost = memory_cost
            self.parallelism = parallelism
            self._lib = ctypes.CDLL("libargon2.so.1")
            self._lib.argon2id_hash_encoded.argtypes = [
                ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                ctypes.c_char_p, ctypes.c_size_t,
                ctypes.c_char_p, ctypes.c_size_t,
                ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t,
            ]
            self._lib.argon2id_hash_encoded.restype = ctypes.c_int
            self._lib.argon2id_verify.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t]
            self._lib.argon2id_verify.restype = ctypes.c_int

        def hash(self, password: str) -> str:
            pwd_bytes = password.encode("utf-8")
            salt = secrets.token_bytes(16)
            encoded_len = 128
            buf = ctypes.create_string_buffer(encoded_len)
            rc = self._lib.argon2id_hash_encoded(
                self.time_cost, self.memory_cost, self.parallelism,
                pwd_bytes, len(pwd_bytes),
                salt, len(salt),
                32, buf, encoded_len,
            )
            if rc != 0:
                raise VerificationError(f"argon2id_hash_encoded failed with code {rc}")
            return buf.value.decode("utf-8")

        def verify(self, encoded: str, password: str) -> bool:
            if not encoded or not encoded.startswith("$argon2id$"):
                raise InvalidHashError("Invalid argon2id hash")
            pwd_bytes = password.encode("utf-8")
            enc_bytes = encoded.encode("utf-8")
            rc = self._lib.argon2id_verify(enc_bytes, pwd_bytes, len(pwd_bytes))
            if rc == 0:
                return True
            raise VerifyMismatchError("Password mismatch")

    PasswordHasher = _LibArgon2Hasher  # type: ignore[misc,assignment]

PASSWORDS = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
LOGIN_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "OWNER": {"*"},
    "ADMIN": {"users:read", "users:create", "users:update", "users:disable", "roles:assign", "audit:read", "portfolio:read", "trades:read", "strategies:read", "backtests:read", "backtests:run", "paper_orders:create", "risk:configure"},
    "TRADER": {"portfolio:read", "trades:read", "strategies:read", "strategies:run", "backtests:read", "backtests:run", "paper_orders:create"},
    "VIEWER": {"portfolio:read", "trades:read", "strategies:read", "backtests:read"},
}
SESSION_COOKIE = "botvex_session"
CSRF_COOKIE = "botvex_csrf"
SESSION_TTL_SECONDS = 8 * 60 * 60
SESSION_IDLE_TTL_SECONDS = 30 * 60
INVITATION_TTL_SECONDS = 24 * 60 * 60


def db_path() -> Path:
    raw = os.getenv("BOTVEX_IDENTITY_DB_PATH", "data/botvex_identity.sqlite3").strip()
    path = Path(raw).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def now_ts() -> int:
    return int(time.time())


def iso(ts: int | None = None) -> str:
    return datetime.fromtimestamp(ts or now_ts(), timezone.utc).isoformat()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def initialize() -> None:
    with connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY,
          normalized_login TEXT NOT NULL UNIQUE,
          password_hash TEXT,
          status TEXT NOT NULL CHECK(status IN ('ACTIVE','PENDING_ACTIVATION','DISABLED','EXPIRED')),
          must_change_password INTEGER NOT NULL DEFAULT 0,
          trading_access TEXT NOT NULL DEFAULT 'read' CHECK(trading_access IN ('read','paper','disabled')),
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          expires_at TEXT,
          last_login_at TEXT,
          created_by TEXT,
          FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_users_status_expiry ON users(status, expires_at);
        CREATE TABLE IF NOT EXISTS roles (
          name TEXT PRIMARY KEY,
          description TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS permissions (
          code TEXT PRIMARY KEY,
          description TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS role_permissions (
          role_name TEXT NOT NULL REFERENCES roles(name) ON DELETE CASCADE,
          permission_code TEXT NOT NULL REFERENCES permissions(code) ON DELETE CASCADE,
          PRIMARY KEY(role_name, permission_code)
        );
        CREATE TABLE IF NOT EXISTS user_roles (
          user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          role TEXT NOT NULL CHECK(role IN ('OWNER','ADMIN','TRADER','VIEWER')),
          PRIMARY KEY(user_id, role)
        );
        CREATE TABLE IF NOT EXISTS sessions (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          token_hash TEXT NOT NULL UNIQUE,
          created_at INTEGER NOT NULL,
          expires_at INTEGER NOT NULL,
          last_seen_at INTEGER NOT NULL DEFAULT 0,
          revoked_at INTEGER,
          user_agent TEXT,
          ip_address TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, expires_at);
        CREATE TABLE IF NOT EXISTS invitations (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          token_hash TEXT NOT NULL UNIQUE,
          purpose TEXT NOT NULL CHECK(purpose IN ('activate','reset')),
          created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
          created_at INTEGER NOT NULL,
          expires_at INTEGER NOT NULL,
          used_at INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_invitations_user ON invitations(user_id, purpose, expires_at);
        CREATE TABLE IF NOT EXISTS audit_logs (
          id TEXT PRIMARY KEY,
          actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
          target_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
          action TEXT NOT NULL,
          outcome TEXT NOT NULL,
          created_at TEXT NOT NULL,
          metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);
        CREATE TABLE IF NOT EXISTS login_attempts (
          key_hash TEXT NOT NULL,
          attempted_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_login_attempts_key_time ON login_attempts(key_hash, attempted_at);
        CREATE TABLE IF NOT EXISTS telegram_accounts (
          telegram_user_id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
          linked_at TEXT NOT NULL
        );
        """)
        session_columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
        if "last_seen_at" not in session_columns:
            conn.execute("ALTER TABLE sessions ADD COLUMN last_seen_at INTEGER NOT NULL DEFAULT 0")
        role_descriptions = {"OWNER": "Полный доступ владельца", "ADMIN": "Делегированное администрирование", "TRADER": "Аналитика и PAPER-операции", "VIEWER": "Только чтение"}
        for role_name, description in role_descriptions.items():
            conn.execute("INSERT OR IGNORE INTO roles(name,description) VALUES(?,?)", (role_name, description))
        permission_descriptions = {
            "users:read": "Просмотр пользователей", "users:create": "Создание пользователей", "users:update": "Изменение пользователей",
            "users:disable": "Отключение пользователей", "roles:assign": "Назначение ролей", "audit:read": "Просмотр журнала аудита",
            "portfolio:read": "Просмотр портфеля", "trades:read": "Просмотр сделок", "strategies:read": "Просмотр стратегий",
            "strategies:run": "Запуск стратегий", "backtests:read": "Просмотр бэктестов", "backtests:run": "Запуск бэктестов",
            "paper_orders:create": "Создание PAPER-ордеров", "risk:configure": "Настройка риск-лимитов",
        }
        for code, description in permission_descriptions.items():
            conn.execute("INSERT OR IGNORE INTO permissions(code,description) VALUES(?,?)", (code, description))
        for role_name, permissions in ROLE_PERMISSIONS.items():
            codes = permission_descriptions.keys() if "*" in permissions else permissions
            for code in codes:
                conn.execute("INSERT OR IGNORE INTO role_permissions(role_name,permission_code) VALUES(?,?)", (role_name, code))


def consume_login_attempt(key: str, limit: int = 10, window_seconds: int = 300) -> bool:
    """Atomically record a login attempt in SQLite, shared across app workers/restarts."""
    initialize()
    now = now_ts()
    key_digest = token_hash("login-rate:" + key)
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM login_attempts WHERE attempted_at < ?", (now - window_seconds,))
        count = conn.execute(
            "SELECT COUNT(*) FROM login_attempts WHERE key_hash=? AND attempted_at>=?",
            (key_digest, now - window_seconds),
        ).fetchone()[0]
        if int(count) >= limit:
            conn.rollback()
            return False
        conn.execute("INSERT INTO login_attempts(key_hash,attempted_at) VALUES(?,?)", (key_digest, now))
        conn.commit()
        return True


def clear_login_attempts(key: str) -> None:
    initialize()
    key_digest = token_hash("login-rate:" + key)
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM login_attempts WHERE key_hash=?", (key_digest,))
        conn.commit()


def _audit(conn: sqlite3.Connection, actor: str | None, target: str | None, action: str, outcome: str = "success", metadata: dict[str, Any] | None = None) -> None:
    conn.execute("INSERT INTO audit_logs(id,actor_user_id,target_user_id,action,outcome,created_at,metadata_json) VALUES(?,?,?,?,?,?,?)",
                 (str(uuid.uuid4()), actor, target, action, outcome, iso(), json.dumps(metadata or {}, separators=(",", ":"))))


def normalize_login(login: str) -> str:
    value = login.strip().lower()
    if not LOGIN_RE.fullmatch(value):
        raise ValueError("Логин должен содержать 3–32 символа: латинские буквы, цифры, точку, дефис или подчёркивание.")
    return value


def create_owner(login: str, password: str) -> str:
    initialize()
    normalized = normalize_login(login)
    if normalized != "lshpek":
        raise ValueError("Первоначальный OWNER должен иметь логин lshpek.")
    if len(password) < 12:
        raise ValueError("Пароль OWNER должен содержать не менее 12 символов.")
    hashed = PASSWORDS.hash(password)
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing_owner = conn.execute("SELECT u.id FROM users u JOIN user_roles r ON r.user_id=u.id WHERE r.role='OWNER'").fetchone()
        if existing_owner:
            conn.rollback()
            raise ValueError("OWNER уже существует; bootstrap не перезаписывает существующий аккаунт.")
        if conn.execute("SELECT 1 FROM users WHERE normalized_login=?", (normalized,)).fetchone():
            conn.rollback()
            raise ValueError("Логин уже существует; безопасный bootstrap остановлен.")
        user_id = str(uuid.uuid4())
        conn.execute("INSERT INTO users(id,normalized_login,password_hash,status,must_change_password,trading_access,created_at,updated_at) VALUES(?,?,?,'ACTIVE',1,'paper',?,?)", (user_id, normalized, hashed, iso(), iso()))
        conn.execute("INSERT INTO user_roles(user_id,role) VALUES(?,'OWNER')", (user_id,))
        _audit(conn, user_id, user_id, "owner.bootstrap")
        conn.commit()
        return user_id


def _user_row(conn: sqlite3.Connection, user_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


def user_roles(conn: sqlite3.Connection, user_id: str) -> list[str]:
    return [r["role"] for r in conn.execute("SELECT role FROM user_roles WHERE user_id=? ORDER BY role", (user_id,)).fetchall()]


def user_payload(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    roles = user_roles(conn, row["id"])
    permissions = {item["permission_code"] for item in conn.execute(
        "SELECT DISTINCT rp.permission_code FROM user_roles ur JOIN role_permissions rp ON rp.role_name=ur.role WHERE ur.user_id=?", (row["id"],)
    ).fetchall()}
    return {"id": row["id"], "login": row["normalized_login"], "role": roles[0] if roles else None,
            "roles": roles, "permissions": sorted(permissions), "status": row["status"],
            "must_change_password": bool(row["must_change_password"]), "trading_access": row["trading_access"],
            "created_at": row["created_at"], "updated_at": row["updated_at"], "expires_at": row["expires_at"],
            "last_login_at": row["last_login_at"], "created_by": row["created_by"]}


def reset_owner_password(password: str) -> str:
    """Local-shell recovery. It never exposes a reset endpoint or preserves old sessions."""
    initialize()
    if len(password) < 12 or len(password) > 256:
        raise ValueError("Пароль OWNER должен содержать 12–256 символов.")
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        owners = conn.execute("SELECT u.id,u.normalized_login FROM users u JOIN user_roles r ON r.user_id=u.id WHERE r.role='OWNER' ORDER BY u.created_at").fetchall()
        if len(owners) != 1:
            conn.rollback()
            raise ValueError("Recovery требует ровно одного OWNER; автоматический выбор небезопасен.")
        owner = owners[0]
        conn.execute("UPDATE users SET password_hash=?,must_change_password=1,status='ACTIVE',updated_at=? WHERE id=?", (PASSWORDS.hash(password), iso(), owner["id"]))
        conn.execute("UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (now_ts(), owner["id"]))
        _audit(conn, owner["id"], owner["id"], "owner.password_recovered", metadata={"method": "local_cli"})
        conn.commit()
        return owner["id"]


def authenticate(login: str, password: str) -> dict[str, Any] | None:
    initialize()
    try:
        normalized = normalize_login(login)
    except ValueError:
        normalized = "invalid-login"
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM users WHERE normalized_login=?", (normalized,)).fetchone()
        if not row or not row["password_hash"]:
            try:
                PASSWORDS.hash(password[:1024] or "invalid-password")
            except Exception:
                pass
            _audit(conn, None, row["id"] if row else None, "auth.login", "failure")
            conn.commit()
            return None
        try:
            PASSWORDS.verify(row["password_hash"], password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            _audit(conn, None, row["id"], "auth.login", "failure")
            conn.commit()
            return None
        if row["status"] != "ACTIVE":
            _audit(conn, None, row["id"], "auth.login", "failure", {"reason": "inactive"})
            conn.commit()
            return None
        if row["expires_at"] and row["expires_at"] <= iso():
            conn.execute("UPDATE users SET status='EXPIRED',updated_at=? WHERE id=?", (iso(), row["id"]))
            conn.execute("UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (now_ts(), row["id"]))
            _audit(conn, None, row["id"], "auth.login", "failure", {"reason": "expired"})
            conn.commit()
            return None
        conn.execute("UPDATE users SET last_login_at=?,updated_at=? WHERE id=?", (iso(), iso(), row["id"]))
        _audit(conn, row["id"], row["id"], "auth.login")
        roles = user_roles(conn, row["id"])
        conn.commit()
        return {"id": row["id"], "login": row["normalized_login"], "must_change_password": bool(row["must_change_password"]), "roles": roles}


def create_session(user_id: str, user_agent: str | None = None, ip_address: str | None = None) -> tuple[str, str, int]:
    initialize()
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    now = now_ts()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO sessions(id,user_id,token_hash,created_at,expires_at,last_seen_at,user_agent,ip_address) VALUES(?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), user_id, token_hash(token), now, now + SESSION_TTL_SECONDS, now, (user_agent or "")[:300], (ip_address or "")[:80]))
        _audit(conn, user_id, user_id, "auth.session_created")
        conn.commit()
    return token, csrf, now + SESSION_TTL_SECONDS


def get_session_user(token: str) -> dict[str, Any] | None:
    initialize()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT s.id AS session_id,s.expires_at AS session_expires,s.last_seen_at AS session_last_seen,s.created_at AS session_created,u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.revoked_at IS NULL", (token_hash(token),)).fetchone()
        if not row or int(row["session_expires"]) <= now_ts():
            conn.commit()
            return None
        if int(row["session_last_seen"] or row["session_created"]) and now_ts() - int(row["session_last_seen"] or row["session_created"]) > SESSION_IDLE_TTL_SECONDS:
            conn.execute("UPDATE sessions SET revoked_at=? WHERE id=?", (now_ts(), row["session_id"]))
            conn.commit()
            return None
        conn.execute("UPDATE sessions SET last_seen_at=? WHERE id=?", (now_ts(), row["session_id"]))
        if row["status"] != "ACTIVE":
            conn.commit()
            return None
        if row["expires_at"] and row["expires_at"] <= iso():
            conn.execute("UPDATE users SET status='EXPIRED',updated_at=? WHERE id=?", (iso(), row["id"]))
            conn.execute("UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (now_ts(), row["id"]))
            conn.commit()
            return None
        payload = user_payload(conn, row)
        payload["session_id"] = row["session_id"]
        payload["session_expires_at"] = int(row["session_expires"])
        conn.commit()
        return payload


def revoke_session(token: str) -> None:
    initialize()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT user_id FROM sessions WHERE token_hash=?", (token_hash(token),)).fetchone()
        conn.execute("UPDATE sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL", (now_ts(), token_hash(token)))
        if row:
            _audit(conn, row["user_id"], row["user_id"], "auth.logout")
        conn.commit()


def revoke_all_sessions(user_id: str, except_token: str | None = None) -> None:
    initialize()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if except_token:
            conn.execute("UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL AND token_hash<>?", (now_ts(), user_id, token_hash(except_token)))
        else:
            conn.execute("UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (now_ts(), user_id))
        conn.commit()


def list_sessions(user_id: str) -> list[dict[str, Any]]:
    initialize()
    with connect() as conn:
        rows = conn.execute("SELECT id,created_at,expires_at,last_seen_at,revoked_at,user_agent,ip_address FROM sessions WHERE user_id=? ORDER BY created_at DESC LIMIT 100", (user_id,)).fetchall()
        return [{**dict(row), "active": row["revoked_at"] is None and row["expires_at"] > now_ts() and now_ts() - row["last_seen_at"] <= SESSION_IDLE_TTL_SECONDS} for row in rows]


def revoke_session_id(user_id: str, session_id: str) -> bool:
    initialize()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT id FROM sessions WHERE id=? AND user_id=?", (session_id, user_id)).fetchone()
        if not row:
            conn.commit()
            return False
        conn.execute("UPDATE sessions SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (now_ts(), session_id))
        _audit(conn, user_id, user_id, "auth.session_revoked", metadata={"session_id": session_id})
        conn.commit()
        return True


def change_password(user_id: str, new_password: str, current_password: str | None = None, bootstrap_change: bool = False) -> None:
    initialize()
    if len(new_password) < 12 or len(new_password) > 256:
        raise ValueError("Пароль должен содержать 12–256 символов.")
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _user_row(conn, user_id)
        if not row or row["status"] != "ACTIVE":
            conn.rollback(); raise ValueError("Аккаунт недоступен.")
        if not bootstrap_change:
            if not current_password or not row["password_hash"]:
                conn.rollback(); raise ValueError("Требуется текущий пароль.")
            try:
                PASSWORDS.verify(row["password_hash"], current_password)
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                conn.rollback(); raise ValueError("Текущий пароль неверен.")
        conn.execute("UPDATE users SET password_hash=?,must_change_password=0,updated_at=? WHERE id=?", (PASSWORDS.hash(new_password), iso(), user_id))
        conn.execute("UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (now_ts(), user_id))
        _audit(conn, user_id, user_id, "auth.password_changed")
        conn.commit()


def create_user(actor_id: str, login: str, role: str, trading_access: str, expiration: str) -> dict[str, Any]:
    initialize()
    normalized = normalize_login(login)
    role = role.upper()
    if role not in {"VIEWER", "TRADER", "ADMIN"}:
        raise ValueError("Недопустимая роль для обычного создания аккаунта.")
    if trading_access not in {"read", "paper", "disabled"}:
        raise ValueError("Недопустимый уровень торгового доступа.")
    if expiration not in {"never", "7_days", "30_days", "90_days"}:
        raise ValueError("Недопустимый срок действия.")
    expiry = None if expiration == "never" else iso(now_ts() + {"7_days": 7, "30_days": 30, "90_days": 90}[expiration] * 86400)
    user_id = str(uuid.uuid4())
    stamp = iso()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        actor = _user_row(conn, actor_id)
        actor_roles = user_roles(conn, actor_id)
        if not actor or actor["status"] != "ACTIVE" or not any(r in {"OWNER", "ADMIN"} for r in actor_roles):
            conn.rollback(); raise PermissionError("Недостаточно прав для создания пользователя.")
        if "ADMIN" in actor_roles and role == "ADMIN":
            conn.rollback(); raise PermissionError("ADMIN не может создавать других ADMIN.")
        try:
            conn.execute("INSERT INTO users(id,normalized_login,password_hash,status,must_change_password,trading_access,created_at,updated_at,expires_at,created_by) VALUES(?,?,NULL,'PENDING_ACTIVATION',0,?,?,?,?,?)", (user_id, normalized, trading_access, stamp, stamp, expiry, actor_id))
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise ValueError("Логин уже существует.") from exc
        conn.execute("INSERT INTO user_roles(user_id,role) VALUES(?,?)", (user_id, role))
        invite_token = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO invitations(id,user_id,token_hash,purpose,created_by,created_at,expires_at) VALUES(?,?,?,'activate',?,?,?)", (str(uuid.uuid4()), user_id, token_hash(invite_token), actor_id, now_ts(), now_ts() + INVITATION_TTL_SECONDS))
        _audit(conn, actor_id, user_id, "users.create", metadata={"role": role, "trading_access": trading_access, "expires_at": expiry})
        conn.commit()
    return get_user(user_id) or {}


def get_user(user_id: str) -> dict[str, Any] | None:
    initialize()
    with connect() as conn:
        row = _user_row(conn, user_id)
        return user_payload(conn, row) if row else None


def list_users(limit: int = 50, offset: int = 0, search: str = "") -> dict[str, Any]:
    initialize()
    limit = max(1, min(limit, 100)); offset = max(0, offset)
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        expired_ids = [row["id"] for row in conn.execute("SELECT id FROM users WHERE status='ACTIVE' AND expires_at IS NOT NULL AND expires_at<=?", (iso(),)).fetchall()]
        if expired_ids:
            conn.executemany("UPDATE users SET status='EXPIRED',updated_at=? WHERE id=?", [(iso(), user_id) for user_id in expired_ids])
            conn.executemany("UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", [(now_ts(), user_id) for user_id in expired_ids])
        conn.commit()
        where = "WHERE normalized_login LIKE ?" if search.strip() else ""
        args: tuple[Any, ...] = (f"%{search.strip().lower()}%",) if where else ()
        total = conn.execute(f"SELECT COUNT(*) FROM users {where}", args).fetchone()[0]
        rows = conn.execute(f"SELECT * FROM users {where} ORDER BY created_at DESC LIMIT ? OFFSET ?", (*args, limit, offset)).fetchall()
        return {"items": [user_payload(conn, row) for row in rows], "total": total, "limit": limit, "offset": offset}


def issue_invitation(actor_id: str, user_id: str, purpose: str = "activate") -> str:
    initialize()
    if purpose not in {"activate", "reset"}:
        raise ValueError("Invalid invitation purpose")
    token = secrets.token_urlsafe(32)
    now = now_ts()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        actor = _user_row(conn, actor_id)
        user = _user_row(conn, user_id)
        actor_roles = user_roles(conn, actor_id)
        target_roles = user_roles(conn, user_id)
        if not actor or actor["status"] != "ACTIVE" or not any(role in {"OWNER", "ADMIN"} for role in actor_roles):
            conn.rollback(); raise PermissionError("Недостаточно прав для выпуска приглашения.")
        if "ADMIN" in actor_roles and set(target_roles).intersection({"OWNER", "ADMIN"}):
            conn.rollback(); raise PermissionError("ADMIN не может выпускать приглашения или сброс пароля для OWNER/ADMIN.")
        if not user or user["status"] in {"DISABLED", "EXPIRED"}:
            conn.rollback(); raise ValueError("Аккаунт не найден или недоступен.")
        if purpose == "activate" and user["status"] != "PENDING_ACTIVATION":
            conn.rollback(); raise ValueError("Ссылка активации доступна только для ожидающего активации аккаунта.")
        if purpose == "reset" and user["status"] != "ACTIVE":
            conn.rollback(); raise ValueError("Сброс пароля доступен только активному аккаунту.")
        conn.execute("UPDATE invitations SET used_at=? WHERE user_id=? AND purpose=? AND used_at IS NULL", (now, user_id, purpose))
        conn.execute("INSERT INTO invitations(id,user_id,token_hash,purpose,created_by,created_at,expires_at) VALUES(?,?,?,?,?,?,?)", (str(uuid.uuid4()), user_id, token_hash(token), purpose, actor_id, now, now + INVITATION_TTL_SECONDS))
        _audit(conn, actor_id, user_id, f"users.invitation_{purpose}_issued")
        conn.commit()
    return token


def activate_invitation(token: str, password: str) -> dict[str, Any]:
    initialize()
    if len(password) < 12 or len(password) > 256:
        raise ValueError("Пароль должен содержать 12–256 символов.")
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        invite = conn.execute("SELECT * FROM invitations WHERE token_hash=? AND used_at IS NULL", (token_hash(token),)).fetchone()
        if not invite or invite["expires_at"] <= now_ts() or invite["purpose"] not in {"activate", "reset"}:
            conn.rollback(); raise ValueError("Ссылка недействительна или истекла.")
        user = _user_row(conn, invite["user_id"])
        if not user or user["status"] in {"DISABLED", "EXPIRED"}:
            conn.rollback(); raise ValueError("Аккаунт недоступен.")
        status_value = "ACTIVE" if invite["purpose"] == "activate" else user["status"]
        conn.execute("UPDATE users SET password_hash=?,status=?,must_change_password=0,updated_at=? WHERE id=?", (PASSWORDS.hash(password), status_value, iso(), user["id"]))
        conn.execute("UPDATE invitations SET used_at=? WHERE id=?", (now_ts(), invite["id"]))
        conn.execute("UPDATE invitations SET used_at=? WHERE user_id=? AND purpose=? AND used_at IS NULL", (now_ts(), user["id"], invite["purpose"]))
        conn.execute("UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (now_ts(), user["id"]))
        _audit(conn, user["id"], user["id"], f"auth.invitation_{invite['purpose']}_consumed")
        conn.commit()
        return {"login": user["normalized_login"], "status": status_value}


def admin_update_user(actor_id: str, user_id: str, *, role: str | None = None, trading_access: str | None = None, status: str | None = None, expiration: str | None = None) -> dict[str, Any]:
    initialize()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        actor = _user_row(conn, actor_id); target = _user_row(conn, user_id)
        actor_roles = user_roles(conn, actor_id)
        if not actor or not target or not actor_roles or not any(r in {"OWNER", "ADMIN"} for r in actor_roles):
            conn.rollback(); raise PermissionError("Недостаточно прав.")
        if "ADMIN" in actor_roles and (role in {"OWNER", "ADMIN"} or set(user_roles(conn, user_id)).intersection({"OWNER", "ADMIN"})):
            conn.rollback(); raise PermissionError("ADMIN не может назначать или изменять аккаунты OWNER/ADMIN.")
        if user_id == actor_id and role and role not in actor_roles:
            conn.rollback(); raise PermissionError("Нельзя повышать собственные привилегии.")
        if role and role not in {"OWNER", "ADMIN", "TRADER", "VIEWER"}:
            conn.rollback(); raise ValueError("Недопустимая роль.")
        if role == "OWNER":
            conn.rollback(); raise ValueError("Назначение OWNER доступно только через отдельную защищённую процедуру assign-owner.")
        if trading_access and trading_access not in {"read", "paper", "disabled"}:
            conn.rollback(); raise ValueError("Недопустимый торговый доступ.")
        if status and status not in {"ACTIVE", "DISABLED", "EXPIRED", "PENDING_ACTIVATION"}:
            conn.rollback(); raise ValueError("Недопустимый статус.")
        if status == "ACTIVE" and not target["password_hash"]:
            conn.rollback(); raise ValueError("Нельзя активировать аккаунт без пароля; выпусти приглашение активации.")
        expiry = target["expires_at"]
        if expiration is not None:
            if expiration not in {"never", "7_days", "30_days", "90_days"}:
                conn.rollback(); raise ValueError("Недопустимый срок действия.")
            expiry = None if expiration == "never" else iso(now_ts() + {"7_days": 7, "30_days": 30, "90_days": 90}[expiration] * 86400)
        if status in {"DISABLED", "EXPIRED"} or role and role != "OWNER":
            owner_count = conn.execute("SELECT COUNT(*) FROM user_roles r JOIN users u ON u.id=r.user_id WHERE r.role='OWNER' AND u.status='ACTIVE'").fetchone()[0]
            if "OWNER" in user_roles(conn, user_id) and owner_count <= 1 and (status in {"DISABLED", "EXPIRED"} or role != "OWNER"):
                conn.rollback(); raise ValueError("Нельзя отключить или понизить последнего активного OWNER.")
        conn.execute("UPDATE users SET trading_access=COALESCE(?,trading_access),status=COALESCE(?,status),expires_at=?,updated_at=? WHERE id=?", (trading_access, status, expiry, iso(), user_id))
        if role:
            conn.execute("DELETE FROM user_roles WHERE user_id=?", (user_id,))
            conn.execute("INSERT INTO user_roles(user_id,role) VALUES(?,?)", (user_id, role))
        if status in {"DISABLED", "EXPIRED"} or role or trading_access:
            conn.execute("UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (now_ts(), user_id))
        _audit(conn, actor_id, user_id, "users.update", metadata={"role": role, "trading_access": trading_access, "status": status, "expires_at": expiry})
        conn.commit()
    return get_user(user_id) or {}


def assign_owner(actor_id: str, target_user_id: str, confirmation_login: str) -> dict[str, Any]:
    """High-privilege owner assignment kept separate from ordinary user updates."""
    initialize()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        actor = _user_row(conn, actor_id)
        target = _user_row(conn, target_user_id)
        if not actor or actor["status"] != "ACTIVE" or "OWNER" not in user_roles(conn, actor_id):
            conn.rollback(); raise PermissionError("Только активный OWNER может назначить OWNER.")
        if not target or target["status"] != "ACTIVE" or not target["password_hash"]:
            conn.rollback(); raise ValueError("Назначить OWNER можно только активному аккаунту с установленным паролем.")
        if normalize_login(confirmation_login) != target["normalized_login"]:
            conn.rollback(); raise ValueError("Подтверждение должно точно совпадать с логином целевого аккаунта.")
        if "OWNER" in user_roles(conn, target_user_id):
            conn.rollback(); raise ValueError("Целевой аккаунт уже имеет роль OWNER.")
        conn.execute("DELETE FROM user_roles WHERE user_id=?", (target_user_id,))
        conn.execute("INSERT INTO user_roles(user_id,role) VALUES(?,'OWNER')", (target_user_id,))
        conn.execute("UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (now_ts(), target_user_id))
        _audit(conn, actor_id, target_user_id, "users.assign_owner", metadata={"confirmed_login": target["normalized_login"]})
        conn.commit()
    return get_user(target_user_id) or {}


def audit_logs(limit: int = 100) -> list[dict[str, Any]]:
    initialize()
    with connect() as conn:
        rows = conn.execute("SELECT id,actor_user_id,target_user_id,action,outcome,created_at,metadata_json FROM audit_logs ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
        return [{**dict(r), "metadata": json.loads(r["metadata_json"])} for r in rows]
