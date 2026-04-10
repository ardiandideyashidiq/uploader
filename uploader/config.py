from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values


DEFAULT_PIXELDRAIN_KEY = "f159c602-0c9f-4c09-8b82-544d6acdb568"
DEFAULT_GOFILE_KEY = "ZCXFB6pBWMEWaCNEARTKCu8j7clo8GNQ"
DEFAULT_TELEGRAM_BOT_TOKEN = "8745418982:AAFuxsUvacKh0eC1gtdPBoH6Ebsrf4TMle0"
DEFAULT_TELEGRAM_CHAT_ID = "6665891737"


def _load_dotenv_values() -> dict[str, str]:
    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        return {}
    return {
        key: value
        for key, value in dotenv_values(env_path).items()
        if key and value is not None
    }


def _pick_value(cli_value: str | None, dotenv_values_map: dict[str, str], *keys: str, default: str | None = None) -> str | None:
    if cli_value:
        return cli_value
    for key in keys:
        env_value = os.getenv(key)
        if env_value:
            return env_value
    for key in keys:
        dotenv_value = dotenv_values_map.get(key)
        if dotenv_value:
            return dotenv_value
    return default


@dataclass(slots=True)
class AppConfig:
    pixeldrain_key: str
    gofile_key: str
    telegram_bot_token: str | None
    telegram_chat_id: str | None

    @classmethod
    def from_sources(
        cls,
        *,
        pixeldrain_key: str | None,
        gofile_key: str | None,
        telegram_bot_token: str | None,
        telegram_chat_id: str | None,
    ) -> "AppConfig":
        dotenv_values_map = _load_dotenv_values()
        return cls(
            pixeldrain_key=_pick_value(
                pixeldrain_key,
                dotenv_values_map,
                "PIXELDRAIN_API_KEY",
                "pixeldrain",
                default=DEFAULT_PIXELDRAIN_KEY,
            ),
            gofile_key=_pick_value(
                gofile_key,
                dotenv_values_map,
                "GOFILE_API_KEY",
                "gofile",
                default=DEFAULT_GOFILE_KEY,
            ),
            telegram_bot_token=_pick_value(
                telegram_bot_token,
                dotenv_values_map,
                "TELEGRAM_BOT_TOKEN",
                "telegram_bot_token",
                default=DEFAULT_TELEGRAM_BOT_TOKEN,
            ),
            telegram_chat_id=_pick_value(
                telegram_chat_id,
                dotenv_values_map,
                "TELEGRAM_CHAT_ID",
                "telegram_chat_id",
                default=DEFAULT_TELEGRAM_CHAT_ID,
            ),
        )
