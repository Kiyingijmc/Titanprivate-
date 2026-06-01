"""Bridge service configuration loaded from environment."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class BridgeSettings(BaseSettings):
    """Configuration for the MT5 bridge service.

    Loaded from environment variables, with .env file support.
    """

    bridge_host: str = "0.0.0.0"
    bridge_port: int = 8766
    bridge_auth_token: str

    mt5_login: int | None = None
    mt5_password: str | None = None
    mt5_server: str | None = None
    mt5_path: str | None = None

    log_level: str = "INFO"
    log_file: str = "logs/bridge.log"

    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent.parent / "config" / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


def get_settings() -> BridgeSettings:
    """Get bridge settings, loaded once."""
    return BridgeSettings()  # type: ignore[call-arg]
