from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field


class IntegrationStatus(BaseModel):
    name: str
    state: Literal["connected", "unavailable", "degraded", "error"]
    detail: str
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DashboardResponse(BaseModel):
    mode: Literal["DEMO", "PAPER"] = "PAPER"
    live_enabled: bool = False
    portfolio_available: bool = False
    balance: float | None = None
    equity: float | None = None
    realized_pnl: float | None = None
    unrealized_pnl: float | None = None
    as_of: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    message: str = "PAPER simulation is available; broker connectivity and live market prices are not configured."
    integrations: list[IntegrationStatus]


class EventItem(BaseModel):
    id: str
    level: Literal["info", "warning", "error"]
    title: str
    detail: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
