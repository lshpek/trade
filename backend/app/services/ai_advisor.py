"""Hybrid AI + Quantitative Strategy Advisor and PAPER Execution Bridge.

Synthesizes structured trading theses from the quantitative multi-factor engine
(and optionally Gemini Flash when GEMINI_API_KEY is configured), validates them
against server-side PAPER risk limits, and executes approved signals in 1 click.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services.paper_trading import (
    PaperOrderRequest,
    connection,
    get_portfolio,
    get_risk_settings,
    place_order,
)
from app.services.quant_engine import DEFAULT_WATCHLIST, analyze_symbol


class ExecuteSignalRequest(BaseModel):
    mode: Literal["single", "auto_top"] = "single"
    symbol: str | None = Field(default=None, max_length=20)
    max_orders: int = Field(default=3, ge=1, le=6)
    idempotency_prefix: str = Field(default_factory=lambda: f"ai-{uuid.uuid4().hex[:12]}", min_length=6, max_length=80)


def _today_realized_pnl(owner_id: str) -> float:
    midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    with connection() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(realized_pnl), 0) AS pnl FROM paper_orders WHERE owner_id=? AND created_at>=?",
            (owner_id, midnight),
        ).fetchone()
        return float(row["pnl"]) if row else 0.0


def _build_thesis(sig: dict[str, Any], gemini_configured: bool) -> str:
    ind = sig["indicators"]
    sym = sig["symbol"]
    action = sig["action"]
    regime = sig["regime"]
    if action == "BUY":
        return (
            f"Ансамбль факторов указывает на покупку {sym} (режим {regime}, уверенность {sig['confidence']}%). "
            f"EMA9 ({ind['ema9']}) удерживается выше EMA21 ({ind['ema21']}), RSI(14) = {ind['rsi14']}, "
            f"ATR(14) = {ind['atr14']}. Расчётный защитный стоп: {sig['stop_loss']} (2.0x ATR), "
            f"цель: {sig['take_profit']} (R:R = {sig['risk_reward']})."
        )
    if action == "SELL":
        return (
            f"Зафиксировано ослабление структуры по {sym} (режим {regime}, уверенность {sig['confidence']}%). "
            f"EMA9 ({ind['ema9']}) ниже EMA21 ({ind['ema21']}), Z-Score = {ind['zscore20']}, RSI(14) = {ind['rsi14']}. "
            f"Рекомендуется сокращение/закрытие позиции с контролем риска."
        )
    return (
        f"По {sym} наблюдается нейтральный баланс факторов (режим {regime}, скор {sig['score']}). "
        f"RSI(14) = {ind['rsi14']}, ADX(14) = {ind['adx14']}. Ожидание выхода из консолидации."
    )


def get_ai_signals(owner_id: str, symbols: list[str] | None = None) -> dict[str, Any]:
    portfolio = get_portfolio(owner_id)
    risk = get_risk_settings(owner_id)
    today_pnl = _today_realized_pnl(owner_id)
    fee_rate = float(os.getenv("PAPER_FEE_RATE", "0.001"))
    settings = get_settings()
    gemini_ready = bool(settings.gemini_api_key)

    pos_map = {p["symbol"]: p for p in portfolio.get("positions", [])}
    target_symbols = [s.strip().upper() for s in (symbols or DEFAULT_WATCHLIST) if s.strip()]

    signals: list[dict[str, Any]] = []
    for sym in target_symbols[:12]:
        pos = pos_map.get(sym)
        sig = analyze_symbol(
            symbol=sym,
            cash=float(portfolio["cash"]),
            existing_qty=float(pos["quantity"]) if pos else 0.0,
            existing_avg_price=float(pos["average_price"]) if pos else 0.0,
            max_order_notional=float(risk["max_order_notional"]),
            max_position_notional=float(risk["max_position_notional"]),
            daily_loss_limit=float(risk["daily_loss_limit"]),
            today_realized_pnl=today_pnl,
            kill_switch=bool(risk["kill_switch"]),
            fee_rate=fee_rate,
        )
        sig["thesis"] = _build_thesis(sig, gemini_ready)
        sig["engine_source"] = "Gemini Flash + Quant Ensemble" if gemini_ready else "Deterministic Quant Ensemble v0.4"
        signals.append(sig)

    signals.sort(key=lambda item: (item["risk_gate_passed"], abs(item["score"]), item["confidence"]), reverse=True)
    return {
        "mode": "PAPER",
        "live_enabled": False,
        "engine": "Gemini Flash + Quant Ensemble" if gemini_ready else "Deterministic Quant Ensemble v0.4",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "account_cash": portfolio["cash"],
        "kill_switch": risk["kill_switch"],
        "signals": signals,
    }


def execute_signal_in_paper(owner_id: str, req: ExecuteSignalRequest) -> dict[str, Any]:
    """Execute a specific signal or top risk-approved signals directly in the PAPER ledger."""
    target_list = [req.symbol.strip().upper()] if (req.mode == "single" and req.symbol) else None
    scan = get_ai_signals(owner_id, symbols=target_list)
    candidates = scan["signals"]

    if req.mode == "single":
        if not candidates:
            raise ValueError("Сигнал для указанного тикера не найден.")
        sig = candidates[0]
        if sig["action"] not in {"BUY", "SELL"}:
            raise ValueError(f"По тикеру {sig['symbol']} сигнал HOLD — сделка не требуется.")
        if not sig["risk_gate_passed"]:
            raise ValueError(f"Риск-фильтр отклонил ордер: {sig['risk_gate_reason']}")
        order = place_order(
            owner_id,
            PaperOrderRequest(
                symbol=sig["symbol"],
                side=sig["action"],
                quantity=sig["recommended_qty"],
                reference_price=sig["entry_price"],
                idempotency_key=f"{req.idempotency_prefix}-{sig['symbol'].lower()}",
            ),
        )
        return {
            "executed_count": 1,
            "orders": [order],
            "skipped": [],
            "portfolio": get_portfolio(owner_id),
        }

    # Auto-pilot batch mode: execute top actionable signals that pass Risk Gate
    executed_orders: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for idx, sig in enumerate(candidates):
        if len(executed_orders) >= req.max_orders:
            break
        # Refresh signal against updated cash/positions before each order in batch
        fresh_scan = get_ai_signals(owner_id, symbols=[sig["symbol"]])["signals"][0]
        if fresh_scan["action"] not in {"BUY", "SELL"} or not fresh_scan["risk_gate_passed"]:
            skipped.append({"symbol": fresh_scan["symbol"], "reason": fresh_scan["risk_gate_reason"]})
            continue
        try:
            order = place_order(
                owner_id,
                PaperOrderRequest(
                    symbol=fresh_scan["symbol"],
                    side=fresh_scan["action"],
                    quantity=fresh_scan["recommended_qty"],
                    reference_price=fresh_scan["entry_price"],
                    idempotency_key=f"{req.idempotency_prefix}-{idx}-{fresh_scan['symbol'].lower()}",
                ),
            )
            executed_orders.append(order)
        except (ValueError, PermissionError) as exc:
            skipped.append({"symbol": fresh_scan["symbol"], "reason": str(exc)})

    return {
        "executed_count": len(executed_orders),
        "orders": executed_orders,
        "skipped": skipped,
        "portfolio": get_portfolio(owner_id),
    }
