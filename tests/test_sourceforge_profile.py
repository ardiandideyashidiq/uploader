from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from uploader.sourceforge_profile import SourceForgeProfile, load_profile, resolve_profile, save_profile


class SourceForgeProfileTests(unittest.TestCase):
    def test_save_and_load_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict("os.environ", {"XDG_CONFIG_HOME": temp_dir}, clear=False):
                profile = SourceForgeProfile(
                    username="user",
                    project="infinity-x",
                    remote_root="/home/frs/project/infinity-x",
                    auth_mode="ssh_key",
                    ssh_key_path="/home/user/.ssh/id_ed25519",
                    password_helper=None,
                    last_remote_dir="P661N/16/vanilla",
                )
                save_profile(profile)
                loaded = load_profile()

        self.assertEqual(loaded, profile)

    def test_resolve_profile_prefers_cli_over_env_and_saved_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                "os.environ",
                {
                    "XDG_CONFIG_HOME": temp_dir,
                    "SOURCEFORGE_USERNAME": "env-user",
                    "SOURCEFORGE_PROJECT": "env-project",
                },
                clear=False,
            ):
                save_profile(SourceForgeProfile(username="saved-user", project="saved-project"))
                resolved = resolve_profile(
                    cli_profile=SourceForgeProfile(username="cli-user", auth_mode="interactive_password")
                )

        self.assertEqual(resolved.username, "cli-user")
        self.assertEqual(resolved.project, "saved-project")
        self.assertEqual(resolved.auth_mode, "interactive_password")

    def test_resolve_profile_uses_dotenv_when_env_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            (temp_path / ".env").write_text("SOURCEFORGE_USERNAME=dot-user\nSOURCEFORGE_PROJECT=dot-project\n")
            with patch.dict("os.environ", {"XDG_CONFIG_HOME": temp_dir}, clear=False), patch("pathlib.Path.cwd", return_value=temp_path):
                resolved = resolve_profile()

        self.assertEqual(resolved.username, "dot-user")
        self.assertEqual(resolved.project, "dot-project")


if __name__ == "__main__":
    unittest.main()
