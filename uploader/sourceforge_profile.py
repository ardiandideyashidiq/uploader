from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path

from dotenv import dotenv_values


PROFILE_FILENAME = "sourceforge.json"


@dataclass(slots=True)
class SourceForgeProfile:
    username: str | None = None
    project: str | None = None
    remote_root: str | None = None
    auth_mode: str | None = None
    ssh_key_path: str | None = None
    password_helper: str | None = None
    last_remote_dir: str | None = None


def get_config_dir() -> Path:
    base = os.getenv("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "uploader"
    return Path.home() / ".config" / "uploader"


def get_profile_path() -> Path:
    return get_config_dir() / PROFILE_FILENAME


def load_profile() -> SourceForgeProfile | None:
    path = get_profile_path()
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return SourceForgeProfile(**data)


def save_profile(profile: SourceForgeProfile) -> None:
    path = get_profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(profile), indent=2, sort_keys=True) + "\n")


def _pick(*values: str | None) -> str | None:
    for value in values:
        if value:
            return value
    return None


def _load_dotenv_values() -> dict[str, str]:
    path = Path.cwd() / ".env"
    if not path.exists():
        return {}
    return {key: value for key, value in dotenv_values(path).items() if key and value}


def resolve_profile(*, cli_profile: SourceForgeProfile | None = None) -> SourceForgeProfile:
    stored = load_profile()

    env = {
        "username": _pick(os.getenv("SOURCEFORGE_USERNAME"), os.getenv("sourceforge_username")),
        "project": _pick(os.getenv("SOURCEFORGE_PROJECT"), os.getenv("sourceforge_project")),
        "remote_root": _pick(os.getenv("SOURCEFORGE_REMOTE_ROOT"), os.getenv("sourceforge_remote_root")),
        "auth_mode": _pick(os.getenv("SOURCEFORGE_AUTH_MODE"), os.getenv("sourceforge_auth_mode")),
        "ssh_key_path": _pick(os.getenv("SOURCEFORGE_SSH_KEY_PATH"), os.getenv("sourceforge_ssh_key_path")),
        "password_helper": _pick(os.getenv("SOURCEFORGE_PASSWORD_HELPER"), os.getenv("sourceforge_password_helper")),
        "last_remote_dir": _pick(os.getenv("SOURCEFORGE_LAST_REMOTE_DIR"), os.getenv("sourceforge_last_remote_dir")),
    }
    dotenv = _load_dotenv_values()

    def dotenv_pick(*keys: str) -> str | None:
        return _pick(*(dotenv.get(key) for key in keys))

    cli_profile = cli_profile or SourceForgeProfile()
    return SourceForgeProfile(
        username=_pick(cli_profile.username, stored.username if stored else None, env["username"], dotenv_pick("SOURCEFORGE_USERNAME", "sourceforge_username")),
        project=_pick(cli_profile.project, stored.project if stored else None, env["project"], dotenv_pick("SOURCEFORGE_PROJECT", "sourceforge_project")),
        remote_root=_pick(cli_profile.remote_root, stored.remote_root if stored else None, env["remote_root"], dotenv_pick("SOURCEFORGE_REMOTE_ROOT", "sourceforge_remote_root")),
        auth_mode=_pick(cli_profile.auth_mode, stored.auth_mode if stored else None, env["auth_mode"], dotenv_pick("SOURCEFORGE_AUTH_MODE", "sourceforge_auth_mode")),
        ssh_key_path=_pick(cli_profile.ssh_key_path, stored.ssh_key_path if stored else None, env["ssh_key_path"], dotenv_pick("SOURCEFORGE_SSH_KEY_PATH", "sourceforge_ssh_key_path")),
        password_helper=_pick(cli_profile.password_helper, stored.password_helper if stored else None, env["password_helper"], dotenv_pick("SOURCEFORGE_PASSWORD_HELPER", "sourceforge_password_helper")),
        last_remote_dir=_pick(cli_profile.last_remote_dir, stored.last_remote_dir if stored else None, env["last_remote_dir"], dotenv_pick("SOURCEFORGE_LAST_REMOTE_DIR", "sourceforge_last_remote_dir")),
    )
