import hashlib
import hmac
import json
from urllib.parse import urlencode
import pytest
from app.auth.telegram import validate_init_data


def signed_init_data(token: str, user_id: int = 123, auth_date: int = 1_700_000_000) -> str:
    fields = {"auth_date": str(auth_date), "query_id": "AAE", "user": json.dumps({"id": user_id, "first_name": "Test"}, separators=(",", ":"))}
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    fields["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_valid_init_data():
    result = validate_init_data(signed_init_data("secret"), "secret", max_age_seconds=86400, now=1_700_000_010)
    assert result["user_id"] == 123


def test_invalid_signature_rejected():
    with pytest.raises(ValueError, match="signature"):
        validate_init_data(signed_init_data("secret") + "x", "secret", now=1_700_000_010)


def test_expired_init_data_rejected():
    with pytest.raises(ValueError, match="expired"):
        validate_init_data(signed_init_data("secret"), "secret", max_age_seconds=10, now=1_700_000_100)


def test_duplicate_init_data_fields_rejected():
    from app.auth.telegram import validate_init_data
    with pytest.raises(ValueError, match="Duplicate"):
        validate_init_data("auth_date=1700000000&auth_date=1700000001&hash=abc&user=%7B%7D", "secret", now=1700000002)
