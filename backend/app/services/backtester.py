"""Event-driven historical OHLCV backtesting engine with realistic fees, slippage, and ATR stops."""
from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field
try:
    from pydantic import field_validator
    _PYDANTIC_V2 = True
except ImportError:
    from pydantic import validator as _v1_validator
    _PYDANTIC_V2 = False

from app.services.paper_trading import connection, initialize as init_paper_db
from app.services.quant_engine import (
    adx_series,
    atr_series,
    bollinger_and_zscore,
    ema,
    get_ohlcv_candles,
    macd,
    rolling_vwap,
    score_candles_at,
    wilder_rsi,
)


class BacktestRunRequest(BaseModel):
    symbol: str = Field(default="NVDA", min_length=1, max_length=20, pattern=r"^[A-Za-z0-9._-]+$") if _PYDANTIC_V2 else Field(default="NVDA", min_length=1, max_length=20, regex=r"^[A-Za-z0-9._-]+$")
    strategy: Literal["ensemble_quant", "ema_trend_atr", "vwap_zscore_reversion"] = "ensemble_quant"
    bars: int = Field(default=240, ge=80, le=800)
    initial_cash: float = Field(default=10000.0, ge=100.0, le=10_000_000.0, allow_inf_nan=False) if _PYDANTIC_V2 else Field(default=10000.0, ge=100.0, le=10_000_000.0)
    fee_bps: float = Field(default=10.0, ge=0.0, le=200.0, allow_inf_nan=False) if _PYDANTIC_V2 else Field(default=10.0, ge=0.0, le=200.0)
    slippage_bps: float = Field(default=5.0, ge=0.0, le=200.0, allow_inf_nan=False) if _PYDANTIC_V2 else Field(default=5.0, ge=0.0, le=200.0)

    if _PYDANTIC_V2:
        @field_validator("symbol")
        @classmethod
        def normalize_symbol(cls, value: str) -> str:
            return value.strip().upper()
    else:
        @_v1_validator("symbol")
        def normalize_symbol(cls, value: str) -> str:
            return value.strip().upper()


def _init_backtest_table() -> None:
    init_paper_db()
    with connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS paper_backtests (
          id TEXT PRIMARY KEY,
          owner_id TEXT NOT NULL,
          symbol TEXT NOT NULL,
          strategy TEXT NOT NULL,
          bars INTEGER NOT NULL,
          initial_cash REAL NOT NULL,
          final_equity REAL NOT NULL,
          total_return_pct REAL NOT NULL,
          benchmark_return_pct REAL NOT NULL,
          alpha_pct REAL NOT NULL,
          sharpe_ratio REAL NOT NULL,
          sortino_ratio REAL NOT NULL,
          max_drawdown_pct REAL NOT NULL,
          win_rate_pct REAL NOT NULL,
          profit_factor REAL NOT NULL,
          expectancy_usd REAL NOT NULL,
          total_trades INTEGER NOT NULL,
          payload_json TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_paper_backtests_owner ON paper_backtests(owner_id, created_at DESC);
        """)


def run_backtest(owner_id: str, req: BacktestRunRequest) -> dict[str, Any]:
    _init_backtest_table()
    candles = get_ohlcv_candles(req.symbol, bars=req.bars)
    closes = [c.close for c in candles]
    e9 = ema(closes, 9)
    e21 = ema(closes, 21)
    e50 = ema(closes, 50)
    rsi = wilder_rsi(closes, 14)
    _, _, hist = macd(closes, 12, 26, 9)
    atr_vals = atr_series(candles, 14)
    adx_vals = adx_series(candles, 14)
    _, _, _, z_vals = bollinger_and_zscore(closes, 20, 2.0)
    vwap_vals = rolling_vwap(candles, 20)

    fee_rate = req.fee_bps / 10_000.0
    slip_rate = req.slippage_bps / 10_000.0

    cash = float(req.initial_cash)
    pos_qty = 0.0
    pos_entry = 0.0
    pos_stop = 0.0
    pos_target = 0.0
    pos_entry_time = ""
    pos_entry_fee = 0.0

    warmup = 35
    start_price = candles[warmup].close
    trades: list[dict[str, Any]] = []
    equity_series: list[dict[str, Any]] = []
    bar_returns: list[float] = []
    prev_equity = cash
    peak_equity = cash
    max_dd_pct = 0.0

    for i in range(warmup, len(candles)):
        bar = candles[i]
        atr_v = max(atr_vals[i], bar.close * 0.005)

        # 1. Check intrabar Stop-Loss / Take-Profit if position is open
        if pos_qty > 0:
            exit_price: float | None = None
            exit_reason = ""
            if bar.low <= pos_stop:
                exit_price = max(0.01, pos_stop * (1.0 - slip_rate))
                exit_reason = "STOP_LOSS"
            elif bar.high >= pos_target:
                exit_price = pos_target * (1.0 - slip_rate)
                exit_reason = "TAKE_PROFIT"
            else:
                # Trailing stop ratchet for profitable trend moves
                if bar.close - pos_entry > 1.5 * atr_v:
                    pos_stop = max(pos_stop, bar.close - 1.6 * atr_v)

                # Strategy exit signal check on close
                should_exit = False
                if req.strategy == "ensemble_quant":
                    snap = score_candles_at(candles, i, e9, e21, e50, rsi, hist, atr_vals, adx_vals, z_vals, vwap_vals)
                    should_exit = snap["action"] == "SELL" or snap["score"] < -15.0
                elif req.strategy == "ema_trend_atr":
                    should_exit = e9[i] < e21[i] and hist[i] < 0
                elif req.strategy == "vwap_zscore_reversion":
                    should_exit = z_vals[i] >= 0.35 or rsi[i] >= 65.0

                if should_exit:
                    exit_price = bar.close * (1.0 - slip_rate)
                    exit_reason = "SIGNAL_EXIT"

            if exit_price is not None:
                gross_notional = pos_qty * exit_price
                exit_fee = gross_notional * fee_rate
                net_pnl = (exit_price - pos_entry) * pos_qty - pos_entry_fee - exit_fee
                ret_pct = (net_pnl / max(pos_qty * pos_entry, 1e-9)) * 100.0
                cash += gross_notional - exit_fee
                trades.append({
                    "entry_time": pos_entry_time,
                    "exit_time": bar.timestamp,
                    "side": "LONG",
                    "quantity": round(pos_qty, 4),
                    "entry_price": round(pos_entry, 4),
                    "exit_price": round(exit_price, 4),
                    "pnl": round(net_pnl, 2),
                    "return_pct": round(ret_pct, 2),
                    "reason": exit_reason,
                })
                pos_qty = 0.0

        # 2. Check entry signal if flat
        if pos_qty == 0 and i < len(candles) - 1:
            enter_long = False
            if req.strategy == "ensemble_quant":
                snap = score_candles_at(candles, i, e9, e21, e50, rsi, hist, atr_vals, adx_vals, z_vals, vwap_vals)
                enter_long = snap["action"] == "BUY" or (snap["score"] >= 18.0 and rsi[i] < 68.0)
            elif req.strategy == "ema_trend_atr":
                enter_long = e9[i] > e21[i] and hist[i] > 0 and 42.0 <= rsi[i] <= 68.0
            elif req.strategy == "vwap_zscore_reversion":
                enter_long = z_vals[i] <= -1.15 or rsi[i] <= 38.0

            if enter_long and cash > 100.0:
                fill_price = bar.close * (1.0 + slip_rate)
                stop_dist = max(atr_v * 1.9, fill_price * 0.012)
                # Position size: risk 1.8% of equity on stop, up to 45% of available cash
                risk_dollars = (cash * 0.018)
                qty_by_risk = risk_dollars / stop_dist
                max_notional = cash * 0.45
                notional = min(qty_by_risk * fill_price, max_notional)
                entry_fee = notional * fee_rate
                if notional > 25.0 and cash >= notional + entry_fee:
                    pos_qty = notional / fill_price
                    pos_entry = fill_price
                    pos_stop = fill_price - stop_dist
                    pos_target = fill_price + (stop_dist * 2.2)
                    pos_entry_time = bar.timestamp
                    pos_entry_fee = entry_fee
                    cash -= (notional + entry_fee)

        # Mark-to-market equity
        curr_equity = cash + (pos_qty * bar.close)
        bar_ret = (curr_equity - prev_equity) / max(prev_equity, 1e-9)
        bar_returns.append(bar_ret)
        prev_equity = curr_equity
        if curr_equity > peak_equity:
            peak_equity = curr_equity
        dd_pct = ((peak_equity - curr_equity) / max(peak_equity, 1e-9)) * 100.0
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

        bench_equity = req.initial_cash * (bar.close / max(start_price, 1e-9))
        equity_series.append({
            "timestamp": bar.timestamp,
            "equity": round(curr_equity, 2),
            "benchmark": round(bench_equity, 2),
            "drawdown_pct": round(-dd_pct, 2),
        })

    # Close any open position at end of backtest window for clean accounting
    if pos_qty > 0:
        last_bar = candles[-1]
        exit_price = last_bar.close * (1.0 - slip_rate)
        gross_notional = pos_qty * exit_price
        exit_fee = gross_notional * fee_rate
        net_pnl = (exit_price - pos_entry) * pos_qty - pos_entry_fee - exit_fee
        ret_pct = (net_pnl / max(pos_qty * pos_entry, 1e-9)) * 100.0
        cash += gross_notional - exit_fee
        trades.append({
            "entry_time": pos_entry_time,
            "exit_time": last_bar.timestamp,
            "side": "LONG",
            "quantity": round(pos_qty, 4),
            "entry_price": round(pos_entry, 4),
            "exit_price": round(exit_price, 4),
            "pnl": round(net_pnl, 2),
            "return_pct": round(ret_pct, 2),
            "reason": "END_OF_WINDOW",
        })
        pos_qty = 0.0
        if equity_series:
            equity_series[-1]["equity"] = round(cash, 2)

    final_equity = round(cash, 2)
    total_return_pct = round(((final_equity - req.initial_cash) / req.initial_cash) * 100.0, 2)
    benchmark_return_pct = round(((candles[-1].close - start_price) / max(start_price, 1e-9)) * 100.0, 2)
    alpha_pct = round(total_return_pct - benchmark_return_pct, 2)

    # Annualized Sharpe & Sortino (assuming 4H bars -> ~1500 bars/year)
    ann_factor = math.sqrt(1500.0)
    mean_ret = sum(bar_returns) / max(1, len(bar_returns))
    std_ret = math.sqrt(sum((r - mean_ret) ** 2 for r in bar_returns) / max(1, len(bar_returns)))
    downside_sq = [min(0.0, r) ** 2 for r in bar_returns]
    downside_std = math.sqrt(sum(downside_sq) / max(1, len(downside_sq)))

    sharpe = round((mean_ret / std_ret) * ann_factor, 2) if std_ret > 1e-12 else 0.0
    sortino = round((mean_ret / downside_std) * ann_factor, 2) if downside_std > 1e-12 else sharpe

    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [abs(t["pnl"]) for t in trades if t["pnl"] < 0]
    win_rate_pct = round((len(wins) / len(trades)) * 100.0, 1) if trades else 0.0
    gross_profit = sum(wins)
    gross_loss = sum(losses)
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 1e-9 else (round(gross_profit, 2) if gross_profit > 0 else 0.0)
    expectancy_usd = round(sum(t["pnl"] for t in trades) / len(trades), 2) if trades else 0.0

    # Downsample equity_curve to max 72 points for crisp UI SVG rendering
    step = max(1, len(equity_series) // 72)
    compact_curve = equity_series[::step]
    if equity_series and compact_curve[-1] != equity_series[-1]:
        compact_curve.append(equity_series[-1])

    run_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    result = {
        "id": run_id,
        "symbol": req.symbol,
        "strategy": req.strategy,
        "bars": req.bars,
        "initial_cash": req.initial_cash,
        "final_equity": final_equity,
        "total_return_pct": total_return_pct,
        "benchmark_return_pct": benchmark_return_pct,
        "alpha_pct": alpha_pct,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "max_drawdown_pct": round(max_dd_pct, 2),
        "win_rate_pct": win_rate_pct,
        "profit_factor": profit_factor,
        "expectancy_usd": expectancy_usd,
        "total_trades": len(trades),
        "fee_bps": req.fee_bps,
        "slippage_bps": req.slippage_bps,
        "equity_curve": compact_curve,
        "trades": trades[-30:],
        "created_at": created_at,
        "simulated": True,
    }

    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """INSERT INTO paper_backtests(
                id, owner_id, symbol, strategy, bars, initial_cash, final_equity,
                total_return_pct, benchmark_return_pct, alpha_pct, sharpe_ratio,
                sortino_ratio, max_drawdown_pct, win_rate_pct, profit_factor,
                expectancy_usd, total_trades, payload_json, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id, owner_id, req.symbol, req.strategy, req.bars, req.initial_cash,
                final_equity, total_return_pct, benchmark_return_pct, alpha_pct,
                sharpe, sortino, round(max_dd_pct, 2), win_rate_pct, profit_factor,
                expectancy_usd, len(trades), json.dumps(result, separators=(",", ":")), created_at,
            ),
        )
        conn.commit()
    return result


def list_backtests(owner_id: str, limit: int = 20) -> list[dict[str, Any]]:
    _init_backtest_table()
    with connection() as conn:
        rows = conn.execute(
            "SELECT payload_json FROM paper_backtests WHERE owner_id=? ORDER BY created_at DESC LIMIT ?",
            (owner_id, max(1, min(limit, 50))),
        ).fetchall()
        return [json.loads(r["payload_json"]) for r in rows]
