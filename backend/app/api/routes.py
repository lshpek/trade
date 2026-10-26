from fastapi import APIRouter, Depends, HTTPException, Query
from app.auth.sessions import require_operator
from app.schemas.dashboard import DashboardResponse, EventItem, IntegrationStatus
from app.services.dashboard import dashboard, recent_events, system_status
from app.services.paper_trading import (
    PaperOrderRequest, RiskSettingsRequest, get_portfolio, list_orders,
    get_risk_settings, set_risk_settings, place_order,
)
from app.services.ai_advisor import ExecuteSignalRequest, execute_signal_in_paper, get_ai_signals
from app.services.backtester import BacktestRunRequest, list_backtests, run_backtest

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_operator)])


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(operator: dict = Depends(require_operator)) -> DashboardResponse:
    return dashboard(str(operator["user_id"]))


@router.get("/system/status", response_model=list[IntegrationStatus])
def get_system_status() -> list[IntegrationStatus]:
    return system_status()


@router.get("/events", response_model=list[EventItem])
def get_events() -> list[EventItem]:
    return recent_events()


# Explicitly simulated PAPER endpoints. They never route orders to a broker.
@router.get("/paper/portfolio")
def paper_portfolio(operator: dict = Depends(require_operator)) -> dict:
    return get_portfolio(str(operator["user_id"]))


@router.get("/paper/orders")
def paper_orders(limit: int = Query(default=100, ge=1, le=200), operator: dict = Depends(require_operator)) -> list[dict]:
    return list_orders(str(operator["user_id"]), limit)


@router.post("/paper/orders", status_code=201)
def create_paper_order(request: PaperOrderRequest, operator: dict = Depends(require_operator)) -> dict:
    try:
        return place_order(str(operator["user_id"]), request)
    except PermissionError as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/paper/risk-settings")
def paper_risk_settings(operator: dict = Depends(require_operator)) -> dict:
    return get_risk_settings(str(operator["user_id"]))


@router.put("/paper/risk-settings")
def update_paper_risk_settings(request: RiskSettingsRequest, operator: dict = Depends(require_operator)) -> dict:
    return set_risk_settings(str(operator["user_id"]), request)


# Quantitative & AI Signal Advisor + 1-click PAPER execution endpoints
@router.get("/ai/signals")
def ai_signals(symbols: str | None = Query(default=None), operator: dict = Depends(require_operator)) -> dict:
    parsed = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else None
    return get_ai_signals(str(operator["user_id"]), symbols=parsed)


@router.post("/ai/execute-signal", status_code=201)
def ai_execute_signal(request: ExecuteSignalRequest, operator: dict = Depends(require_operator)) -> dict:
    try:
        return execute_signal_in_paper(str(operator["user_id"]), request)
    except PermissionError as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# Event-driven Historical Backtester endpoints
@router.post("/backtests/run", status_code=201)
def backtests_run(request: BacktestRunRequest, operator: dict = Depends(require_operator)) -> dict:
    try:
        return run_backtest(str(operator["user_id"]), request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/backtests")
def backtests_list(limit: int = Query(default=20, ge=1, le=50), operator: dict = Depends(require_operator)) -> list[dict]:
    return list_backtests(str(operator["user_id"]), limit)
