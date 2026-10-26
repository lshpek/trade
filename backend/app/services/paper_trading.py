"""Transactional, explicitly simulated PAPER trading backed by SQLite.

This module never contacts a broker or market-data provider. Orders are filled at the
user-supplied reference/limit price and are labeled as simulations in API responses.
"""
from __future__ import annotations

import os
import sqlite3
import math
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal

import pydantic
from pydantic import BaseModel, Field
try:
    from pydantic import field_validator
    _PYDANTIC_V2 = True
except ImportError:
    from pydantic import validator as _v1_validator
    _PYDANTIC_V2 = False

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "botvex_paper.sqlite3"


def _db_path() -> Path:
    raw = os.getenv("BOTVEX_DB_PATH", str(DEFAULT_DB)).strip()
    path = Path(raw).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_db_path(), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    try:
        yield conn
    finally:
        conn.close()


def initialize() -> None:
    with connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS paper_accounts (
          owner_id TEXT PRIMARY KEY,
          cash REAL NOT NULL CHECK(cash >= 0),
          initial_cash REAL NOT NULL CHECK(initial_cash > 0),
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS paper_positions (
          owner_id TEXT NOT NULL,
          symbol TEXT NOT NULL,
          quantity REAL NOT NULL CHECK(quantity >= 0),
          average_price REAL NOT NULL CHECK(average_price >= 0),
          PRIMARY KEY(owner_id, symbol),
          FOREIGN KEY(owner_id) REFERENCES paper_accounts(owner_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS paper_orders (
          id TEXT PRIMARY KEY,
          owner_id TEXT NOT NULL,
          idempotency_key TEXT NOT NULL,
          symbol TEXT NOT NULL,
          side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
          quantity REAL NOT NULL,
          reference_price REAL NOT NULL,
          notional REAL NOT NULL,
          fee REAL NOT NULL,
          realized_pnl REAL NOT NULL DEFAULT 0,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(owner_id, idempotency_key),
          FOREIGN KEY(owner_id) REFERENCES paper_accounts(owner_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS paper_settings (
          owner_id TEXT PRIMARY KEY,
          max_order_notional REAL NOT NULL,
          max_position_notional REAL NOT NULL,
          daily_loss_limit REAL NOT NULL,
          kill_switch INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY(owner_id) REFERENCES paper_accounts(owner_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_paper_orders_owner_created ON paper_orders(owner_id, created_at DESC);
        """)
        # Forward-compatible migration for databases created by an earlier starter build.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(paper_orders)").fetchall()}
        if "realized_pnl" not in columns:
            conn.execute("ALTER TABLE paper_orders ADD COLUMN realized_pnl REAL NOT NULL DEFAULT 0")


def _str_field(min_length: int, max_length: int, pattern: str):
    return Field(min_length=min_length, max_length=max_length, pattern=pattern) if _PYDANTIC_V2 else Field(min_length=min_length, max_length=max_length, regex=pattern)


def _float_field(gt: float, le: float):
    return Field(gt=gt, le=le, allow_inf_nan=False) if _PYDANTIC_V2 else Field(gt=gt, le=le)


class PaperOrderRequest(BaseModel):
    symbol: str = _str_field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9._-]+$")
    side: Literal["BUY", "SELL"]
    quantity: float = _float_field(gt=0, le=1_000_000)
    reference_price: float = _float_field(gt=0, le=1_000_000_000)
    idempotency_key: str = _str_field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")

    if _PYDANTIC_V2:
        @field_validator("symbol")
        @classmethod
        def normalize_symbol(cls, value: str) -> str:
            return value.strip().upper()
    else:
        @_v1_validator("symbol")
        def normalize_symbol(cls, value: str) -> str:
            return value.strip().upper()

        @_v1_validator("quantity", "reference_price")
        def reject_inf_nan(cls, value: float) -> float:
            if not math.isfinite(value):
                raise ValueError("Value must be a finite number")
            return value


class RiskSettingsRequest(BaseModel):
    max_order_notional: float = _float_field(gt=0, le=1_000_000_000)
    max_position_notional: float = _float_field(gt=0, le=1_000_000_000)
    daily_loss_limit: float = _float_field(gt=0, le=1_000_000_000)
    kill_switch: bool = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_account(conn: sqlite3.Connection, owner_id: str) -> None:
    initial = float(os.getenv("PAPER_INITIAL_CASH", "10000"))
    if not math.isfinite(initial) or initial <= 0:
        raise RuntimeError("PAPER_INITIAL_CASH must be a finite positive number")
    conn.execute("INSERT OR IGNORE INTO paper_accounts(owner_id,cash,initial_cash,created_at) VALUES(?,?,?,?)", (owner_id, initial, initial, _now()))
    conn.execute("INSERT OR IGNORE INTO paper_settings(owner_id,max_order_notional,max_position_notional,daily_loss_limit,kill_switch) VALUES(?,?,?,?,0)", (owner_id, initial * .25, initial * .5, initial * .05))


def _account_dict(conn: sqlite3.Connection, owner_id: str) -> dict:
    _ensure_account(conn, owner_id)
    account = conn.execute("SELECT * FROM paper_accounts WHERE owner_id=?", (owner_id,)).fetchone()
    positions = conn.execute("SELECT symbol,quantity,average_price FROM paper_positions WHERE owner_id=? AND quantity>0 ORDER BY symbol", (owner_id,)).fetchall()
    # No live price feed is connected: equity is cash + position cost basis, not mark-to-market.
    position_cost = sum(float(p["quantity"]) * float(p["average_price"]) for p in positions)
    return {
        "mode": "PAPER", "live_enabled": False, "simulated": True,
        "initial_cash": account["initial_cash"], "cash": account["cash"],
        "position_cost_basis": round(position_cost, 8),
        "equity_at_cost_basis": round(float(account["cash"]) + position_cost, 8),
        "positions": [dict(p) for p in positions],
        "price_data_available": False,
        "message": "Виртуальный счёт. Рыночные котировки не подключены; оценка позиций использует цену симуляции, а не текущую рыночную цену."
    }


def get_portfolio(owner_id: str) -> dict:
    initialize()
    with connection() as conn:
        conn.execute("BEGIN")
        result = _account_dict(conn, owner_id)
        conn.commit()
        return result


def get_realized_pnl(owner_id: str) -> float:
    initialize()
    with connection() as conn:
        row = conn.execute("SELECT COALESCE(SUM(realized_pnl),0) AS pnl FROM paper_orders WHERE owner_id=?", (owner_id,)).fetchone()
        return round(float(row["pnl"]), 8)


def list_orders(owner_id: str, limit: int = 100) -> list[dict]:
    initialize()
    with connection() as conn:
        rows = conn.execute("SELECT id,symbol,side,quantity,reference_price,notional,fee,realized_pnl,status,created_at FROM paper_orders WHERE owner_id=? ORDER BY created_at DESC LIMIT ?", (owner_id, max(1, min(limit, 200)))).fetchall()
        return [dict(row) | {"simulated": True, "price_source": "user_supplied_reference_price"} for row in rows]


def get_risk_settings(owner_id: str) -> dict:
    initialize()
    with connection() as conn:
        conn.execute("BEGIN")
        _ensure_account(conn, owner_id)
        row = conn.execute("SELECT max_order_notional,max_position_notional,daily_loss_limit,kill_switch FROM paper_settings WHERE owner_id=?", (owner_id,)).fetchone()
        conn.commit()
        return dict(row) | {"kill_switch": bool(row["kill_switch"]), "live_trading_allowed": False}


def set_risk_settings(owner_id: str, settings: RiskSettingsRequest) -> dict:
    initialize()
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_account(conn, owner_id)
        conn.execute("UPDATE paper_settings SET max_order_notional=?,max_position_notional=?,daily_loss_limit=?,kill_switch=? WHERE owner_id=?", (settings.max_order_notional, settings.max_position_notional, settings.daily_loss_limit, int(settings.kill_switch), owner_id))
        conn.commit()
    return get_risk_settings(owner_id)


def place_order(owner_id: str, request: PaperOrderRequest) -> dict:
    initialize()
    notional = request.quantity * request.reference_price
    if not math.isfinite(notional) or notional <= 0:
        raise ValueError("Order notional must be finite and positive")
    fee_rate = float(os.getenv("PAPER_FEE_RATE", "0.001"))
    if not math.isfinite(fee_rate) or fee_rate < 0 or fee_rate > 0.1:
        raise RuntimeError("PAPER_FEE_RATE must be between 0 and 0.1")
    fee = notional * fee_rate
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_account(conn, owner_id)
        prior = conn.execute("SELECT id,symbol,side,quantity,reference_price,notional,fee,realized_pnl,status,created_at FROM paper_orders WHERE owner_id=? AND idempotency_key=?", (owner_id, request.idempotency_key)).fetchone()
        if prior:
            if (prior["symbol"] != request.symbol or prior["side"] != request.side or float(prior["quantity"]) != request.quantity or float(prior["reference_price"]) != request.reference_price):
                conn.rollback()
                raise ValueError("Idempotency key was already used with a different order payload")
            conn.commit()
            return dict(prior) | {"simulated": True, "idempotent_replay": True, "price_source": "user_supplied_reference_price"}
        account = conn.execute("SELECT cash FROM paper_accounts WHERE owner_id=?", (owner_id,)).fetchone()
        risk = conn.execute("SELECT * FROM paper_settings WHERE owner_id=?", (owner_id,)).fetchone()
        if risk["kill_switch"]:
            conn.rollback()
            raise PermissionError("PAPER kill switch is enabled; new orders are blocked")
        if notional > float(risk["max_order_notional"]):
            conn.rollback()
            raise ValueError("Order exceeds max_order_notional risk limit")
        position = conn.execute("SELECT quantity,average_price FROM paper_positions WHERE owner_id=? AND symbol=?", (owner_id, request.symbol)).fetchone()
        old_qty = float(position["quantity"]) if position else 0.0
        old_avg = float(position["average_price"]) if position else 0.0
        realized_pnl = 0.0
        if request.side == "BUY":
            total_cost = round(notional + fee, 8)
            if float(account["cash"]) + 1e-12 < total_cost:
                conn.rollback()
                raise ValueError("Insufficient virtual cash for order and fee")
            new_qty = round(old_qty + request.quantity, 8)
            new_cost_basis = (old_qty * old_avg) + notional + fee
            new_avg = round(new_cost_basis / new_qty, 8)
            effective_pos_notional = max(new_qty * request.reference_price, new_qty * new_avg)
            if effective_pos_notional > float(risk["max_position_notional"]) + 1e-9:
                conn.rollback()
                raise ValueError("Order would exceed max_position_notional risk limit")
            new_cash = round(max(0.0, float(account["cash"]) - total_cost), 8)
            conn.execute("UPDATE paper_accounts SET cash=? WHERE owner_id=?", (new_cash, owner_id))
            conn.execute("INSERT INTO paper_positions(owner_id,symbol,quantity,average_price) VALUES(?,?,?,?) ON CONFLICT(owner_id,symbol) DO UPDATE SET quantity=excluded.quantity,average_price=excluded.average_price", (owner_id, request.symbol, new_qty, new_avg))
        else:
            if request.quantity > old_qty + 1e-12:
                conn.rollback()
                raise ValueError("Insufficient virtual position quantity to sell")
            new_qty = round(max(0.0, old_qty - request.quantity), 8)
            realized_pnl = round((request.reference_price - old_avg) * request.quantity - fee, 8)
            midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            today_realized = conn.execute("SELECT COALESCE(SUM(realized_pnl),0) AS pnl FROM paper_orders WHERE owner_id=? AND created_at>=?", (owner_id, midnight)).fetchone()["pnl"]
            if float(today_realized) + realized_pnl < -float(risk["daily_loss_limit"]):
                conn.rollback()
                raise ValueError("Order would exceed daily realized-loss risk limit")
            new_cash = round(max(0.0, float(account["cash"]) + notional - fee), 8)
            conn.execute("UPDATE paper_accounts SET cash=? WHERE owner_id=?", (new_cash, owner_id))
            if new_qty <= 1e-12:
                conn.execute("DELETE FROM paper_positions WHERE owner_id=? AND symbol=?", (owner_id, request.symbol))
            else:
                conn.execute("UPDATE paper_positions SET quantity=? WHERE owner_id=? AND symbol=?", (new_qty, owner_id, request.symbol))
        order_id = str(uuid.uuid4())
        created = _now()
        conn.execute("INSERT INTO paper_orders(id,owner_id,idempotency_key,symbol,side,quantity,reference_price,notional,fee,realized_pnl,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (order_id, owner_id, request.idempotency_key, request.symbol, request.side, request.quantity, request.reference_price, notional, fee, realized_pnl, "SIMULATED_FILLED", created))
        conn.commit()
        return {"id": order_id, "symbol": request.symbol, "side": request.side, "quantity": request.quantity, "reference_price": request.reference_price, "notional": round(notional, 8), "fee": round(fee, 8), "realized_pnl": round(realized_pnl, 8), "status": "SIMULATED_FILLED", "created_at": created, "simulated": True, "idempotent_replay": False, "price_source": "user_supplied_reference_price", "warning": "No broker or market data provider was contacted. This is a paper simulation only."}
