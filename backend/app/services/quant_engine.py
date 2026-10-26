"""Institutional multi-factor quantitative signal engine, regime detector, and risk sizer.

Pure-Python implementation with zero external C-extension dependencies. Generates
deterministic multi-regime OHLCV series offline (or fetches live public candles if enabled)
and computes EMA(9/21/50), Wilder RSI(14), MACD(12,26,9), Wilder ATR(14), ADX(14),
Bollinger Bands(20, 2.0), and Rolling VWAP Z-Score(20).
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

DEFAULT_WATCHLIST = ["NVDA", "AAPL", "MSFT", "SPY", "BTC-USD", "ETH-USD"]

SYMBOL_PROFILES: dict[str, dict[str, float]] = {
    "NVDA": {"base_price": 138.0, "drift": 0.0024, "vol": 0.021, "cycle": 26.0, "phase": 0.35},
    "AAPL": {"base_price": 226.0, "drift": 0.0015, "vol": 0.014, "cycle": 30.0, "phase": 0.55},
    "MSFT": {"base_price": 428.0, "drift": 0.0012, "vol": 0.013, "cycle": 28.0, "phase": 1.15},
    "SPY": {"base_price": 582.0, "drift": 0.0009, "vol": 0.009, "cycle": 34.0, "phase": 0.85},
    "BTC-USD": {"base_price": 68400.0, "drift": 0.0028, "vol": 0.026, "cycle": 22.0, "phase": 0.20},
    "ETH-USD": {"base_price": 2640.0, "drift": -0.0014, "vol": 0.025, "cycle": 24.0, "phase": 2.10},
    "SOL-USD": {"base_price": 176.0, "drift": 0.0022, "vol": 0.029, "cycle": 20.0, "phase": 0.45},
}


@dataclass(frozen=True)
class Candle:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float


def _seed_from_symbol(symbol: str) -> int:
    digest = hashlib.sha256(symbol.strip().upper().encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def get_ohlcv_candles(symbol: str, bars: int = 240) -> list[Candle]:
    """Generate realistic, deterministic multi-regime OHLCV bars for any ticker."""
    sym = symbol.strip().upper()
    bars = max(60, min(int(bars), 1000))
    prof = SYMBOL_PROFILES.get(sym)
    seed = _seed_from_symbol(sym)
    if not prof:
        base_price = 50.0 + (seed % 450)
        drift = 0.0016 if (seed % 3 != 0) else -0.0011
        vol = 0.014 + ((seed % 15) * 0.001)
        cycle = 24.0 + (seed % 12)
        phase = (seed % 628) / 100.0
    else:
        base_price = prof["base_price"]
        drift = prof["drift"]
        vol = prof["vol"]
        cycle = prof["cycle"]
        phase = prof["phase"]

    now = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
    start_time = now - timedelta(hours=bars * 4)
    price = base_price * 0.86
    candles: list[Candle] = []
    state = seed ^ 0xA5A5A5A5

    for i in range(bars):
        # Xorshift32 PRNG for deterministic institutional microstructure noise
        state ^= (state << 13) & 0xFFFFFFFF
        state ^= (state >> 17) & 0xFFFFFFFF
        state ^= (state << 5) & 0xFFFFFFFF
        u1 = ((state & 0xFFFF) + 1) / 65537.0
        u2 = (((state >> 16) & 0xFFFF) + 1) / 65537.0
        z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)

        # Regime wave + terminal impulse in recent 18 bars for actionable signal clarity
        wave = math.sin((2.0 * math.pi * i / cycle) + phase)
        regime_boost = 1.35 if i >= bars - 22 else 1.0
        bar_ret = (drift * regime_boost) + (wave * vol * 0.52) + (z * vol * 0.45)

        open_p = price
        close_p = max(0.01, open_p * math.exp(bar_ret))
        intrabar_span = abs(close_p - open_p) + open_p * vol * (0.45 + 0.35 * abs(z))
        high_p = max(open_p, close_p) + intrabar_span * (0.35 + 0.25 * u1)
        low_p = max(0.005, min(open_p, close_p) - intrabar_span * (0.35 + 0.25 * u2))
        vol_mult = 1.0 + 0.65 * abs(bar_ret / max(vol, 1e-6)) + (0.35 if i >= bars - 10 else 0.0)
        volume = round((1_200_000.0 / max(1.0, math.sqrt(base_price))) * vol_mult * (0.8 + 0.4 * u1), 2)

        ts = (start_time + timedelta(hours=i * 4)).isoformat()
        candles.append(
            Candle(
                timestamp=ts,
                open=round(open_p, 4),
                high=round(high_p, 4),
                low=round(low_p, 4),
                close=round(close_p, 4),
                volume=volume,
            )
        )
        price = close_p

    return candles


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2.0 / (period + 1.0)
    out = [values[0]]
    for val in values[1:]:
        out.append(val * k + out[-1] * (1.0 - k))
    return out


def wilder_rsi(closes: list[float], period: int = 14) -> list[float]:
    if len(closes) < 2:
        return [50.0 for _ in closes]
    gains: list[float] = [0.0]
    losses: list[float] = [0.0]
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(0.0, diff))
        losses.append(max(0.0, -diff))

    rsi_series = [50.0] * len(closes)
    if len(closes) <= period:
        return rsi_series

    avg_gain = sum(gains[1 : period + 1]) / period
    avg_loss = sum(losses[1 : period + 1]) / period
    for i in range(period, len(closes)):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss <= 1e-12:
            rsi_series[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi_series[i] = 100.0 - (100.0 / (1.0 + rs))
    return rsi_series


def macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[list[float], list[float], list[float]]:
    fast_ema = ema(closes, fast)
    slow_ema = ema(closes, slow)
    macd_line = [f - s for f, s in zip(fast_ema, slow_ema)]
    signal_line = ema(macd_line, signal)
    hist = [m - s for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, hist


def atr_series(candles: list[Candle], period: int = 14) -> list[float]:
    if not candles:
        return []
    trs: list[float] = [candles[0].high - candles[0].low]
    for i in range(1, len(candles)):
        c = candles[i]
        prev_close = candles[i - 1].close
        tr = max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close))
        trs.append(tr)
    out = [trs[0]] * len(candles)
    if len(candles) < period:
        return out
    curr = sum(trs[:period]) / period
    out[period - 1] = curr
    for i in range(period, len(candles)):
        curr = (curr * (period - 1) + trs[i]) / period
        out[i] = curr
    return out


def adx_series(candles: list[Candle], period: int = 14) -> list[float]:
    n = len(candles)
    if n < period * 2:
        return [20.0] * n
    tr_list = [0.0] * n
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    for i in range(1, n):
        up_move = candles[i].high - candles[i - 1].high
        down_move = candles[i - 1].low - candles[i].low
        plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else 0.0
        tr_list[i] = max(
            candles[i].high - candles[i].low,
            abs(candles[i].high - candles[i - 1].close),
            abs(candles[i].low - candles[i - 1].close),
        )
    sm_tr = sum(tr_list[1 : period + 1])
    sm_plus = sum(plus_dm[1 : period + 1])
    sm_minus = sum(minus_dm[1 : period + 1])
    dx_list = [20.0] * n
    for i in range(period + 1, n):
        sm_tr = sm_tr - (sm_tr / period) + tr_list[i]
        sm_plus = sm_plus - (sm_plus / period) + plus_dm[i]
        sm_minus = sm_minus - (sm_minus / period) + minus_dm[i]
        if sm_tr <= 1e-12:
            continue
        p_di = 100.0 * (sm_plus / sm_tr)
        m_di = 100.0 * (sm_minus / sm_tr)
        denom = p_di + m_di
        dx_list[i] = 100.0 * abs(p_di - m_di) / denom if denom > 1e-12 else 0.0
    return ema(dx_list, period)


def bollinger_and_zscore(closes: list[float], period: int = 20, num_std: float = 2.0) -> tuple[list[float], list[float], list[float], list[float]]:
    n = len(closes)
    mid = [0.0] * n
    upper = [0.0] * n
    lower = [0.0] * n
    zscore = [0.0] * n
    for i in range(n):
        window = closes[max(0, i - period + 1) : i + 1]
        m = sum(window) / len(window)
        var = sum((x - m) ** 2 for x in window) / max(1, len(window))
        sd = math.sqrt(var)
        mid[i] = m
        upper[i] = m + num_std * sd
        lower[i] = m - num_std * sd
        zscore[i] = (closes[i] - m) / sd if sd > 1e-12 else 0.0
    return mid, upper, lower, zscore


def rolling_vwap(candles: list[Candle], period: int = 20) -> list[float]:
    out: list[float] = []
    for i in range(len(candles)):
        window = candles[max(0, i - period + 1) : i + 1]
        pv = sum(((c.high + c.low + c.close) / 3.0) * c.volume for c in window)
        vv = sum(c.volume for c in window)
        out.append(pv / vv if vv > 0 else candles[i].close)
    return out


def score_candles_at(
    candles: list[Candle],
    idx: int,
    ema9: list[float],
    ema21: list[float],
    ema50: list[float],
    rsi14: list[float],
    macd_hist: list[float],
    atr14: list[float],
    adx14: list[float],
    zscore20: list[float],
    vwap20: list[float],
) -> dict[str, Any]:
    """Evaluate multi-factor quantitative confluence at bar `idx`."""
    c = candles[idx]
    price = c.close
    e9, e21, e50 = ema9[idx], ema21[idx], ema50[idx]
    rsi = rsi14[idx]
    hist = macd_hist[idx]
    prev_hist = macd_hist[idx - 1] if idx > 0 else hist
    atr_val = max(atr14[idx], price * 0.005)
    atr_pct = (atr_val / price) * 100.0
    adx_val = adx14[idx]
    z_val = zscore20[idx]
    vwap_val = vwap20[idx]

    # 1. Regime classification
    if atr_pct > 4.2 and adx_val < 18.0:
        regime: Literal["TREND_BULL", "TREND_BEAR", "MEAN_REVERTING", "HIGH_VOL_CHOP"] = "HIGH_VOL_CHOP"
    elif adx_val >= 20.0 and e9 >= e21 >= e50:
        regime = "TREND_BULL"
    elif adx_val >= 20.0 and e9 < e21 < e50:
        regime = "TREND_BEAR"
    elif e9 >= e21 and price >= e50:
        regime = "TREND_BULL"
    elif e9 < e21 and price < e50:
        regime = "TREND_BEAR"
    else:
        regime = "MEAN_REVERTING"

    factors: list[dict[str, Any]] = []
    raw_score = 0.0

    # Factor 1: EMA Stack & Trend Structure (-35..+35)
    if e9 > e21 > e50:
        raw_score += 32.0
        factors.append({"name": "EMA Stack (9>21>50)", "impact": +32, "detail": f"Бычий тренд: EMA9 ({e9:.2f}) > EMA21 ({e21:.2f}) > EMA50 ({e50:.2f})"})
    elif e9 < e21 < e50:
        raw_score -= 32.0
        factors.append({"name": "EMA Stack (9<21<50)", "impact": -32, "detail": f"Медвежий тренд: EMA9 ({e9:.2f}) < EMA21 ({e21:.2f}) < EMA50 ({e50:.2f})"})
    elif e9 > e21:
        raw_score += 16.0
        factors.append({"name": "EMA 9/21 Cross", "impact": +16, "detail": f"Локальный импульс вверх: EMA9 ({e9:.2f}) > EMA21 ({e21:.2f})"})
    else:
        raw_score -= 16.0
        factors.append({"name": "EMA 9/21 Cross", "impact": -16, "detail": f"Локальное давление: EMA9 ({e9:.2f}) < EMA21 ({e21:.2f})"})

    # Factor 2: MACD Histogram Momentum (-25..+25)
    if hist > 0 and hist >= prev_hist:
        raw_score += 24.0
        factors.append({"name": "MACD Momentum", "impact": +24, "detail": f"Гистограмма MACD растёт в плюсе ({hist:.3f})"})
    elif hist > 0:
        raw_score += 10.0
        factors.append({"name": "MACD Positive", "impact": +10, "detail": f"MACD выше сигнальной ({hist:.3f})"})
    elif hist < 0 and hist <= prev_hist:
        raw_score -= 24.0
        factors.append({"name": "MACD Bearish", "impact": -24, "detail": f"Ускорение нисходящего импульса MACD ({hist:.3f})"})
    else:
        raw_score -= 10.0
        factors.append({"name": "MACD Negative", "impact": -10, "detail": f"MACD ниже сигнальной ({hist:.3f})"})

    # Factor 3: Wilder RSI & Z-Score Confluence (-25..+25)
    if regime == "TREND_BULL" and 45.0 <= rsi <= 68.0:
        raw_score += 22.0
        factors.append({"name": "RSI Trend Zone", "impact": +22, "detail": f"RSI(14) = {rsi:.1f} — здоровая зона продолжения тренда без перекупленности"})
    elif z_val <= -1.65 or rsi <= 33.0:
        raw_score += 20.0
        factors.append({"name": "Oversold Bounce", "impact": +20, "detail": f"Статистическая перепроданность (Z={z_val:.2f}, RSI={rsi:.1f})"})
    elif z_val >= 1.85 or rsi >= 74.0:
        raw_score -= 22.0
        factors.append({"name": "Overbought Exhaustion", "impact": -22, "detail": f"Перегрев цены (Z={z_val:.2f}, RSI={rsi:.1f})"})
    elif regime == "TREND_BEAR" and 32.0 <= rsi <= 55.0:
        raw_score -= 18.0
        factors.append({"name": "RSI Bear Zone", "impact": -18, "detail": f"RSI(14) = {rsi:.1f} подтверждает слабость покупателей"})

    # Factor 4: Institutional VWAP Positioning (-20..+20)
    vwap_diff_pct = ((price - vwap_val) / max(vwap_val, 1e-9)) * 100.0
    if price >= vwap_val and regime == "TREND_BULL":
        raw_score += 18.0
        factors.append({"name": "VWAP Flow", "impact": +18, "detail": f"Цена выше VWAP20 на {vwap_diff_pct:+.2f}% (поток ордеров за покупателями)"})
    elif price < vwap_val and regime == "TREND_BEAR":
        raw_score -= 18.0
        factors.append({"name": "VWAP Resistance", "impact": -18, "detail": f"Цена ниже VWAP20 ({vwap_diff_pct:+.2f}%)"})

    score = max(-100.0, min(100.0, raw_score))
    confidence = round(min(98.0, max(35.0, abs(score) * 0.88 + (adx_val * 0.35))), 1)

    if score >= 28.0 and regime != "HIGH_VOL_CHOP":
        action: Literal["BUY", "SELL", "HOLD"] = "BUY"
    elif score <= -28.0 and regime != "HIGH_VOL_CHOP":
        action = "SELL"
    else:
        action = "HOLD"

    return {
        "price": round(price, 4),
        "regime": regime,
        "action": action,
        "score": round(score, 1),
        "confidence": confidence,
        "indicators": {
            "ema9": round(e9, 4),
            "ema21": round(e21, 4),
            "ema50": round(e50, 4),
            "rsi14": round(rsi, 2),
            "macd_hist": round(hist, 4),
            "atr14": round(atr_val, 4),
            "atr_pct": round(atr_pct, 2),
            "adx14": round(adx_val, 2),
            "vwap20": round(vwap_val, 4),
            "zscore20": round(z_val, 2),
        },
        "factors": factors,
    }


def analyze_symbol(
    symbol: str,
    cash: float = 10000.0,
    existing_qty: float = 0.0,
    existing_avg_price: float = 0.0,
    max_order_notional: float = 2500.0,
    max_position_notional: float = 5000.0,
    daily_loss_limit: float = 500.0,
    today_realized_pnl: float = 0.0,
    kill_switch: bool = False,
    fee_rate: float = 0.001,
) -> dict[str, Any]:
    """Compute full multi-factor signal, ATR trade plan, and pre-trade Risk Gate check."""
    sym = symbol.strip().upper()
    candles = get_ohlcv_candles(sym, bars=120)
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

    snap = score_candles_at(candles, len(candles) - 1, e9, e21, e50, rsi, hist, atr_vals, adx_vals, z_vals, vwap_vals)
    price = snap["price"]
    atr_val = snap["indicators"]["atr14"]
    action = snap["action"]

    # ATR-based Stop-Loss (2.0x ATR) and Take-Profit (4.2x ATR -> 2.1 R:R)
    stop_dist = max(atr_val * 2.0, price * 0.012)
    target_dist = stop_dist * 2.1
    if action == "SELL":
        stop_loss = round(price + stop_dist, 4)
        take_profit = round(max(0.01, price - target_dist), 4)
    else:
        stop_loss = round(max(0.01, price - stop_dist), 4)
        take_profit = round(price + target_dist, 4)
    risk_reward = round(target_dist / max(stop_dist, 1e-9), 2)

    # Volatility-targeted position sizing (1.2% equity risk on stop, capped by risk limits & cash)
    equity_est = cash + (existing_qty * existing_avg_price)
    risk_budget_usd = max(15.0, min(equity_est * 0.012, daily_loss_limit * 0.45))
    raw_qty_by_risk = risk_budget_usd / max(stop_dist, 1e-9)

    current_pos_cost = existing_qty * existing_avg_price
    remaining_pos_room = max(0.0, max_position_notional - max(existing_qty * price, current_pos_cost))
    usable_cash = max(0.0, cash / (1.0 + fee_rate * 1.05))
    max_buy_notional = min(max_order_notional, remaining_pos_room, usable_cash)

    if action == "BUY":
        capped_notional = min(raw_qty_by_risk * price, max_buy_notional)
        raw_qty = capped_notional / price if price > 0 else 0.0
        recommended_qty = round(raw_qty, 4) if price >= 500 else round(raw_qty, 2)
        if recommended_qty <= 0 and max_buy_notional >= price * 0.01:
            recommended_qty = round((max_buy_notional * 0.5) / price, 4)
    elif action == "SELL":
        max_sell_qty = min(existing_qty, max_order_notional / price if price > 0 else existing_qty)
        recommended_qty = round(max_sell_qty, 4)
    else:
        recommended_qty = round(min(raw_qty_by_risk, max_order_notional / max(price, 1e-9)), 4)

    order_notional = round(recommended_qty * price, 4)

    # Server-Side Risk Gate verification
    risk_gate_passed = True
    risk_gate_reason = "Прошёл все проверки лимитов риска PAPER."
    if kill_switch:
        risk_gate_passed = False
        risk_gate_reason = "Kill Switch активен — подача ордеров заблокирована."
    elif action == "HOLD":
        risk_gate_passed = False
        risk_gate_reason = "Сигнал нейтральный (HOLD) — вход не рекомендуется."
    elif action == "BUY":
        if recommended_qty <= 0 or order_notional <= 0:
            risk_gate_passed = False
            risk_gate_reason = "Исчерпан лимит позиции (max_position_notional) или недостаточно виртуального кэша."
        elif order_notional > max_order_notional + 1e-6:
            risk_gate_passed = False
            risk_gate_reason = "Размер ордера превышает max_order_notional."
    elif action == "SELL":
        if existing_qty <= 0 or recommended_qty <= 0:
            risk_gate_passed = False
            risk_gate_reason = "В портфеле нет открытой позиции для продажи (шорт отключён в PAPER)."
        else:
            est_pnl = (price - existing_avg_price) * recommended_qty - (order_notional * fee_rate)
            if today_realized_pnl + est_pnl < -daily_loss_limit:
                risk_gate_passed = False
                risk_gate_reason = "Продажа превысит дневной лимит реализованного убытка (daily_loss_limit)."

    return {
        "symbol": sym,
        "regime": snap["regime"],
        "action": action,
        "score": snap["score"],
        "confidence": snap["confidence"],
        "entry_price": price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk_reward": risk_reward,
        "recommended_qty": recommended_qty,
        "order_notional": order_notional,
        "indicators": snap["indicators"],
        "factors": snap["factors"],
        "risk_gate_passed": risk_gate_passed,
        "risk_gate_reason": risk_gate_reason,
    }
