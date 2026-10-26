import os
from functools import lru_cache
from pathlib import Path

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class Settings(BaseSettings):
        app_name: str = "BOTVEX AI Trader"
        app_env: str = "development"
        log_level: str = "INFO"
        telegram_bot_token: str = ""
        telegram_auth_max_age_seconds: int = 86400
        dev_auth_enabled: bool = False
        gemini_api_key: str = ""
        gemini_model: str = "gemini-2.5-flash"

        model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
except ImportError:
    from pydantic import BaseModel

    def _load_dotenv() -> dict[str, str]:
        values: dict[str, str] = {}
        env_path = Path(".env")
        if env_path.is_file():
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip().strip('"').strip("'")
        return values

    class Settings(BaseModel):
        app_name: str = "BOTVEX AI Trader"
        app_env: str = "development"
        log_level: str = "INFO"
        telegram_bot_token: str = ""
        telegram_auth_max_age_seconds: int = 86400
        dev_auth_enabled: bool = False
        gemini_api_key: str = ""
        gemini_model: str = "gemini-2.5-flash"

        def __init__(self, **data):
            file_vals = _load_dotenv()
            merged = {
                "app_name": os.getenv("APP_NAME", file_vals.get("APP_NAME", "BOTVEX AI Trader")),
                "app_env": os.getenv("APP_ENV", file_vals.get("APP_ENV", "development")),
                "log_level": os.getenv("LOG_LEVEL", file_vals.get("LOG_LEVEL", "INFO")),
                "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", file_vals.get("TELEGRAM_BOT_TOKEN", "")),
                "telegram_auth_max_age_seconds": int(os.getenv("TELEGRAM_AUTH_MAX_AGE_SECONDS", file_vals.get("TELEGRAM_AUTH_MAX_AGE_SECONDS", "86400"))),
                "dev_auth_enabled": os.getenv("DEV_AUTH_ENABLED", file_vals.get("DEV_AUTH_ENABLED", "false")).lower() in {"1", "true", "yes"},
                "gemini_api_key": os.getenv("GEMINI_API_KEY", file_vals.get("GEMINI_API_KEY", "")),
                "gemini_model": os.getenv("GEMINI_MODEL", file_vals.get("GEMINI_MODEL", "gemini-2.5-flash")),
            }
            merged.update(data)
            super().__init__(**merged)


@lru_cache
def get_settings() -> Settings:
    return Settings()
