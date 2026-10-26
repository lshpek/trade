from datetime import datetime, timezone
from app.schemas.dashboard import DashboardResponse, EventItem, IntegrationStatus
from app.core.config import get_settings
from app.services.paper_trading import get_portfolio, get_realized_pnl


def system_status() -> list[IntegrationStatus]:
    now = datetime.now(timezone.utc)
    settings = get_settings()
    auth_configured = bool(settings.telegram_bot_token)
    gemini_configured = bool(getattr(settings, "gemini_api_key", ""))
    return [
        IntegrationStatus(name="API", state="connected", detail="Backend process is responding.", checked_at=now),
        IntegrationStatus(name="Telegram auth", state="connected" if auth_configured else "unavailable", detail="Bot token is configured; Telegram accounts must be linked to an application user." if auth_configured else "Set TELEGRAM_BOT_TOKEN to enable verified Telegram account linking.", checked_at=now),
        IntegrationStatus(name="Quant & AI Signal Engine", state="connected", detail="Multi-factor Quant Ensemble (EMA/RSI/MACD/ATR/VWAP/Z-Score) + Gemini Flash advisor active." if gemini_configured else "Multi-factor Quant Ensemble (EMA/RSI/MACD/ATR/VWAP/Z-Score) active; set GEMINI_API_KEY for LLM thesis enrichment.", checked_at=now),
        IntegrationStatus(name="PAPER engine", state="connected", detail="SQLite-backed virtual accounts, risk gate, and simulated orders are available. No broker is contacted.", checked_at=now),
        IntegrationStatus(name="Historical Backtester", state="connected", detail="Event-driven OHLCV backtester with fees, slippage, and ATR stops is available.", checked_at=now),
        IntegrationStatus(name="Broker / live market data", state="unavailable", detail="No broker is connected; live execution is disabled by design.", checked_at=now),
        IntegrationStatus(name="SQLite PAPER store", state="connected", detail="Local SQLite persistence is implemented. Production durability requires a persistent mounted volume or managed database.", checked_at=now),
    ]


def dashboard(owner_id: str) -> DashboardResponse:
    portfolio = get_portfolio(owner_id)
    realized_pnl = get_realized_pnl(owner_id)
    return DashboardResponse(
        mode="PAPER", live_enabled=False, portfolio_available=True,
        balance=portfolio["cash"], equity=portfolio["equity_at_cost_basis"],
        realized_pnl=round(realized_pnl, 8), unrealized_pnl=None,
        integrations=system_status(),
        message="Virtual PAPER account. Equity uses position cost basis because live market prices are unavailable.",
    )


def recent_events() -> list[EventItem]:
    now = datetime.now(timezone.utc)
    return [
        EventItem(id="starter-001", level="warning", title="PAPER simulation active", detail="Orders are virtual simulations. No broker orders are sent.", created_at=now),
        EventItem(id="starter-002", level="info", title="Quant & Backtest modules ready", detail="Multi-factor signal scanner, ATR risk sizing, and historical backtesting are active in PAPER mode.", created_at=now),
    ]
