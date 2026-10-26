from fastapi.testclient import TestClient
from app.main import app
from app.core.config import get_settings


def test_health_is_available_without_auth():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["live_enabled"] is False


def test_dashboard_requires_auth(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "dev_auth_enabled", False)
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    client = TestClient(app)
    response = client.get("/api/v1/dashboard")
    assert response.status_code == 401


def test_dashboard_returns_virtual_paper_account_in_dev(monkeypatch, tmp_path):
    monkeypatch.setenv("BOTVEX_DB_PATH", str(tmp_path / "dashboard.sqlite3"))
    monkeypatch.setenv("PAPER_INITIAL_CASH", "10000")
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "dev_auth_enabled", True)
    client = TestClient(app)
    response = client.get("/api/v1/dashboard")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "PAPER"
    assert payload["live_enabled"] is False
    assert payload["balance"] == 10000
    assert payload["portfolio_available"] is True
    assert payload["unrealized_pnl"] is None
    assert payload["live_enabled"] is False
