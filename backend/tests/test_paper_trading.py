import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import get_settings
from app.services import paper_trading


@pytest.fixture()
def client_and_db(tmp_path, monkeypatch):
    monkeypatch.setenv("BOTVEX_DB_PATH", str(tmp_path / "paper.sqlite3"))
    monkeypatch.setenv("PAPER_INITIAL_CASH", "10000")
    monkeypatch.setenv("PAPER_FEE_RATE", "0.001")
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "dev_auth_enabled", True)
    paper_trading.initialize()
    return TestClient(app)


def test_paper_buy_is_simulated_and_persistent(client_and_db):
    client = client_and_db
    portfolio = client.get("/api/v1/paper/portfolio").json()
    assert portfolio["simulated"] is True
    assert portfolio["cash"] == 10000
    response = client.post("/api/v1/paper/orders", json={"symbol":"AAPL","side":"BUY","quantity":2,"reference_price":100,"idempotency_key":"buy-aapl-0001"})
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "SIMULATED_FILLED"
    assert response.json()["price_source"] == "user_supplied_reference_price"
    updated = client.get("/api/v1/paper/portfolio").json()
    assert updated["cash"] == pytest.approx(9799.8)
    assert updated["positions"][0]["quantity"] == 2
    assert len(client.get("/api/v1/paper/orders").json()) == 1


def test_idempotency_prevents_double_order(client_and_db):
    client = client_and_db
    payload = {"symbol":"MSFT","side":"BUY","quantity":1,"reference_price":100,"idempotency_key":"msft-buy-0001"}
    first = client.post("/api/v1/paper/orders", json=payload).json()
    second = client.post("/api/v1/paper/orders", json=payload).json()
    assert first["id"] == second["id"]
    assert second["idempotent_replay"] is True
    assert len(client.get("/api/v1/paper/orders").json()) == 1


def test_insufficient_cash_or_position_is_rejected(client_and_db):
    client = client_and_db
    buy = client.post("/api/v1/paper/orders", json={"symbol":"AAPL","side":"BUY","quantity":100,"reference_price":100,"idempotency_key":"large-buy-001"})
    assert buy.status_code == 422
    sell = client.post("/api/v1/paper/orders", json={"symbol":"AAPL","side":"SELL","quantity":1,"reference_price":100,"idempotency_key":"sell-empty-001"})
    assert sell.status_code == 422


def test_risk_limit_and_kill_switch_block_orders(client_and_db):
    client = client_and_db
    settings = {"max_order_notional":100,"max_position_notional":500,"daily_loss_limit":100,"kill_switch":False}
    assert client.put("/api/v1/paper/risk-settings", json=settings).status_code == 200
    too_large = client.post("/api/v1/paper/orders", json={"symbol":"AAPL","side":"BUY","quantity":2,"reference_price":100,"idempotency_key":"risk-limit-001"})
    assert too_large.status_code == 422
    settings["kill_switch"] = True
    assert client.put("/api/v1/paper/risk-settings", json=settings).status_code == 200
    blocked = client.post("/api/v1/paper/orders", json={"symbol":"AAPL","side":"BUY","quantity":1,"reference_price":50,"idempotency_key":"kill-switch-001"})
    assert blocked.status_code == 423


def test_invalid_nan_order_rejected(client_and_db):
    response = client_and_db.post("/api/v1/paper/orders", json={"symbol":"AAPL","side":"BUY","quantity":"NaN","reference_price":100,"idempotency_key":"invalid-nan-001"})
    assert response.status_code == 422


def test_sell_closes_position_and_records_realized_pnl(client_and_db):
    client = client_and_db
    buy = client.post("/api/v1/paper/orders", json={"symbol":"AAPL","side":"BUY","quantity":2,"reference_price":100,"idempotency_key":"aapl-buy-0001"})
    assert buy.status_code == 201
    sell = client.post("/api/v1/paper/orders", json={"symbol":"AAPL","side":"SELL","quantity":2,"reference_price":110,"idempotency_key":"aapl-sell-0001"})
    assert sell.status_code == 201, sell.text
    assert sell.json()["realized_pnl"] == pytest.approx(19.58)
    portfolio = client.get("/api/v1/paper/portfolio").json()
    assert portfolio["positions"] == []
    assert portfolio["cash"] == pytest.approx(10019.58)


def test_idempotency_key_cannot_be_reused_for_different_order(client_and_db):
    client = client_and_db
    payload = {"symbol":"MSFT","side":"BUY","quantity":1,"reference_price":100,"idempotency_key":"reuse-key-0001"}
    assert client.post("/api/v1/paper/orders", json=payload).status_code == 201
    payload["quantity"] = 2
    response = client.post("/api/v1/paper/orders", json=payload)
    assert response.status_code == 422


def test_users_have_separate_paper_accounts(client_and_db):
    client = client_and_db
    first = client.get("/api/v1/paper/portfolio").json()
    assert first["cash"] == 10000
    # Verify that the store isolates records for a distinct application user ID.
    other = paper_trading.get_portfolio("456")
    assert other["cash"] == 10000
    assert other["positions"] == []


def test_daily_realized_loss_limit_blocks_loss_exceeding_sell(client_and_db):
    client = client_and_db
    buy = client.post("/api/v1/paper/orders", json={"symbol":"AAPL","side":"BUY","quantity":2,"reference_price":100,"idempotency_key":"loss-buy-0001"})
    assert buy.status_code == 201
    settings = {"max_order_notional":1000,"max_position_notional":1000,"daily_loss_limit":5,"kill_switch":False}
    assert client.put("/api/v1/paper/risk-settings", json=settings).status_code == 200
    sell = client.post("/api/v1/paper/orders", json={"symbol":"AAPL","side":"SELL","quantity":2,"reference_price":90,"idempotency_key":"loss-sell-0001"})
    assert sell.status_code == 422
    portfolio = client.get("/api/v1/paper/portfolio").json()
    assert portfolio["positions"][0]["quantity"] == 2
