"""Telegram Mini App initData verification per Telegram's documented HMAC scheme."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int = 86400, now: int | None = None) -> dict:
    if not init_data or not bot_token:
        raise ValueError("Missing Telegram initData or bot token")
    parsed_pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    if len({key for key, _ in parsed_pairs}) != len(parsed_pairs):
        raise ValueError("Duplicate Telegram initData fields")
    pairs = dict(parsed_pairs)
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise ValueError("Missing hash")
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise ValueError("Invalid Telegram initData signature")
    try:
        auth_date = int(pairs["auth_date"])
    except (KeyError, ValueError) as exc:
        raise ValueError("Missing or invalid auth_date") from exc
    current = int(time.time()) if now is None else now
    if auth_date > current + 60:
        raise ValueError("auth_date is in the future")
    if current - auth_date > max_age_seconds:
        raise ValueError("Telegram initData has expired")
    user_raw = pairs.get("user")
    if not user_raw:
        raise ValueError("Missing Telegram user")
    try:
        user = json.loads(user_raw)
        user_id = int(user["id"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid Telegram user payload") from exc
    return {"user_id": user_id, "username": user.get("username"), "first_name": user.get("first_name", "")}

