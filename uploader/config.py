from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import dotenv_values


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "uploader" / "config"


def _load_yaml_config(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    try:
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _load_dotenv_values() -> dict[str, str]:
    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        return {}
    return {
        key: value
        for key, value in dotenv_values(env_path).items()
        if key and value is not None
    }


def get_config_path(cli_config: str | None) -> Path:
    if cli_config:
        return Path(cli_config)
    env_config = os.getenv("UPLOADER_CONFIG")
    if env_config:
        return Path(env_config)
    return DEFAULT_CONFIG_PATH


def _pick_value(
    cli_value: str | None,
    yaml_config: dict,
    dotenv_values_map: dict[str, str],
    *keys: str,
    default: str | None = None,
) -> str | None:
    if cli_value:
        return cli_value
    for key in keys:
        yaml_value = yaml_config.get(key)
        if yaml_value:
            return yaml_value
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
    vikingfile_user: str
    telegram_bot_token: str | None
    telegram_chat_id: str | None

    @classmethod
    def from_sources(
        cls,
        *,
        config_path: Path | None = None,
        pixeldrain_key: str | None = None,
        gofile_key: str | None = None,
        vikingfile_user: str | None = None,
        telegram_bot_token: str | None = None,
        telegram_chat_id: str | None = None,
    ) -> "AppConfig":
        yaml_config = _load_yaml_config(config_path or DEFAULT_CONFIG_PATH)
        dotenv_values_map = _load_dotenv_values()
        return cls(
            pixeldrain_key=_pick_value(
                pixeldrain_key,
                yaml_config,
                dotenv_values_map,
                "PIXELDRAIN_API_KEY",
                "pixeldrain_key",
                "pixeldrain",
            )
            or "",
            gofile_key=_pick_value(
                gofile_key,
                yaml_config,
                dotenv_values_map,
                "GOFILE_API_KEY",
                "gofile_key",
                "gofile",
            )
            or "",
            vikingfile_user=_pick_value(
                vikingfile_user,
                yaml_config,
                dotenv_values_map,
                "VIKINGFILE_USER",
                "vikingfile_user",
            )
            or "",
            telegram_bot_token=_pick_value(
                telegram_bot_token,
                yaml_config,
                dotenv_values_map,
                "TELEGRAM_BOT_TOKEN",
                "telegram_bot_token",
            ),
            telegram_chat_id=_pick_value(
                telegram_chat_id,
                yaml_config,
                dotenv_values_map,
                "TELEGRAM_CHAT_ID",
                "telegram_chat_id",
            ),
        )
