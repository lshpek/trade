import sqlite3
import pytest
from fastapi.testclient import TestClient

from app.auth.identity import PASSWORDS, create_owner, create_user
from app.core.config import get_settings
from app.main import app


@pytest.fixture()
def pro_env(tmp_path, monkeypatch):
    monkeypatch.setenv("BOTVEX_IDENTITY_DB_PATH", str(tmp_path / "identity.sqlite3"))
    monkeypatch.setenv("BOTVEX_DB_PATH", str(tmp_path / "paper.sqlite3"))
    monkeypatch.setenv("PAPER_INITIAL_CASH", "10000")
    monkeypatch.setenv("PAPER_FEE_RATE", "0.001")
    monkeypatch.setenv("APP_ENV", "development")
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "dev_auth_enabled", True)
    yield tmp_path
    get_settings.cache_clear()


def test_ai_signals_and_one_click_paper_execution(pro_env):
    client = TestClient(app)
    res = client.get("/api/v1/ai/signals?symbols=NVDA,AAPL,BTC-USD")
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["mode"] == "PAPER"
    assert payload["live_enabled"] is False
    assert len(payload["signals"]) == 3

    buy_signals = [s for s in payload["signals"] if s["action"] == "BUY" and s["risk_gate_passed"]]
    assert len(buy_signals) >= 1
    target_sym = buy_signals[0]["symbol"]

    exec_res = client.post(
        "/api/v1/ai/execute-signal",
        json={"mode": "single", "symbol": target_sym, "idempotency_prefix": "test-sig-001"},
    )
    assert exec_res.status_code == 201, exec_res.text
    exec_data = exec_res.json()
    assert exec_data["executed_count"] == 1
    assert exec_data["orders"][0]["symbol"] == target_sym
    assert exec_data["portfolio"]["cash"] < 10000.0


def test_auto_top_signal_execution_respects_risk_limits(pro_env):
    client = TestClient(app)
    res = client.post(
        "/api/v1/ai/execute-signal",
        json={"mode": "auto_top", "max_orders": 2, "idempotency_prefix": "test-auto-001"},
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["executed_count"] >= 1
    assert len(data["portfolio"]["positions"]) >= 1


def test_backtester_runs_and_persists_metrics(pro_env):
    client = TestClient(app)
    for strategy in ("ensemble_quant", "ema_trend_atr", "vwap_zscore_reversion"):
        run = client.post(
            "/api/v1/backtests/run",
            json={
                "symbol": "NVDA",
                "strategy": strategy,
                "bars": 180,
                "initial_cash": 10000,
                "fee_bps": 10,
                "slippage_bps": 5,
            },
        )
        assert run.status_code == 201, run.text
        body = run.json()
        assert body["symbol"] == "NVDA"
        assert body["strategy"] == strategy
        assert body["simulated"] is True
        assert len(body["equity_curve"]) >= 10
        assert isinstance(body["sharpe_ratio"], (int, float))

    history = client.get("/api/v1/backtests")
    assert history.status_code == 200
    assert len(history.json()) == 3


def test_admin_with_read_trading_access_can_configure_risk_settings(pro_env, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "dev_auth_enabled", False)
    owner_id = create_owner("lshpek", "correct horse battery staple")
    admin_user = create_user(owner_id, "riskadmin", "ADMIN", "read", "never")
    with sqlite3.connect(pro_env / "identity.sqlite3") as conn:
        conn.execute(
            "UPDATE users SET status='ACTIVE', password_hash=?, must_change_password=0 WHERE id=?",
            (PASSWORDS.hash("admin strong password 123"), admin_user["id"]),
        )
        conn.commit()

    client = TestClient(app)
    login_res = client.post("/api/v1/auth/login", json={"login": "riskadmin", "password": "admin strong password 123"})
    assert login_res.status_code == 200
    csrf = client.cookies.get("botvex_csrf")

    # ADMIN with trading_access='read' MUST be allowed to configure risk settings (BUG-02 fix)
    risk_put = client.put(
        "/api/v1/paper/risk-settings",
        headers={"X-CSRF-Token": csrf},
        json={"max_order_notional": 1500, "max_position_notional": 4000, "daily_loss_limit": 300, "kill_switch": False},
    )
    assert risk_put.status_code == 200, risk_put.text
    assert risk_put.json()["max_order_notional"] == 1500

    # But the same ADMIN with trading_access='read' cannot place PAPER orders
    order_post = client.post(
        "/api/v1/paper/orders",
        headers={"X-CSRF-Token": csrf},
        json={"symbol": "AAPL", "side": "BUY", "quantity": 1, "reference_price": 100, "idempotency_key": "adm-read-001"},
    )
    assert order_post.status_code == 403


def test_low_reference_price_cannot_bypass_max_position_notional(pro_env):
    client = TestClient(app)
    client.put(
        "/api/v1/paper/risk-settings",
        json={"max_order_notional": 2500, "max_position_notional": 2500, "daily_loss_limit": 500, "kill_switch": False},
    )
    first = client.post(
        "/api/v1/paper/orders",
        json={"symbol": "AAPL", "side": "BUY", "quantity": 24, "reference_price": 100, "idempotency_key": "pos-cap-1"},
    )
    assert first.status_code == 201
    # Attempting to buy more with an artificially low price (e.g., $10) when cost basis is already $2402.4
    bypass = client.post(
        "/api/v1/paper/orders",
        json={"symbol": "AAPL", "side": "BUY", "quantity": 20, "reference_price": 10, "idempotency_key": "pos-cap-2"},
    )
    assert bypass.status_code == 422
