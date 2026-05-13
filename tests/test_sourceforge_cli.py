from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from uploader.sourceforge_cli import main
from uploader.sourceforge_profile import SourceForgeProfile


class SourceForgeCliTests(unittest.TestCase):
    def _make_file(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temp_dir = tempfile.TemporaryDirectory()
        file_path = Path(temp_dir.name) / "ROM.zip"
        file_path.write_bytes(b"hello world")
        return temp_dir, file_path

    def test_default_prints_help(self) -> None:
        with patch("sys.stdout", new=io.StringIO()) as stdout:
            exit_code = main([])

        self.assertEqual(exit_code, 0)
        self.assertIn("usage: uploader sourceforge", stdout.getvalue())
        self.assertIn("{upload,list,rename,delete,link}", stdout.getvalue())

    @patch("uploader.sourceforge_cli.SourceForgeClient")
    def test_upload_flag_routes_to_client(self, mock_client) -> None:
        mock_client.return_value.upload_file.return_value.url = "https://sourceforge.net/projects/infinity-x/files/a/b/ROM.zip/download"

        with patch("sys.stdout", new=io.StringIO()) as stdout:
            exit_code = main([
                "upload",
                "ROM.zip",
                "--username", "user",
                "--project", "infinity-x",
                "--remote-dir", "P661N/16/vanilla",
                "--no-telegram",
            ])

        self.assertEqual(exit_code, 0)
        self.assertIn("download", stdout.getvalue())
        mock_client.return_value.upload_file.assert_called_once_with(Path("ROM.zip"), "P661N/16/vanilla", overwrite=False)

    @patch("uploader.sourceforge_cli.SourceForgeClient")
    def test_upload_accepts_remote_dir_then_file_positionals(self, mock_client) -> None:
        mock_client.return_value.upload_file.return_value.url = "https://sourceforge.net/projects/rdndds-release/files/release/test/test2/README.md/download"

        with patch("sys.stdout", new=io.StringIO()) as stdout:
            exit_code = main([
                "upload",
                "release/test/test2/",
                "README.md",
                "--username", "user",
                "--project", "rdndds-release",
                "--no-telegram",
            ])

        self.assertEqual(exit_code, 0)
        self.assertIn("download", stdout.getvalue())
        mock_client.return_value.upload_file.assert_called_once_with(Path("README.md"), "release/test/test2/", overwrite=False)

    @patch("uploader.sourceforge_cli.SourceForgeClient")
    def test_upload_remote_dir_flag_overrides_positional_remote_dir(self, mock_client) -> None:
        mock_client.return_value.upload_file.return_value.url = "https://sourceforge.net/projects/rdndds-release/files/override/README.md/download"

        with patch("sys.stdout", new=io.StringIO()):
            exit_code = main([
                "upload",
                "release/test/test2/",
                "README.md",
                "--remote-dir", "override",
                "--username", "user",
                "--project", "rdndds-release",
                "--no-telegram",
            ])

        self.assertEqual(exit_code, 0)
        mock_client.return_value.upload_file.assert_called_once_with(Path("README.md"), "override", overwrite=False)

    @patch("uploader.sourceforge_cli.SourceForgeClient")
    def test_main_uses_process_argv_when_argv_is_none(self, mock_client) -> None:
        mock_client.return_value.upload_file.return_value.url = "https://sourceforge.net/projects/infinity-x/files/a/b/ROM.zip/download"

        with (
            patch.object(
                sys,
                "argv",
                [
                    "up-sf",
                    "upload",
                    "ROM.zip",
                    "--username",
                    "user",
                    "--project",
                    "infinity-x",
                    "--remote-dir",
                    "P661N/16/vanilla",
                    "--no-telegram",
                ],
            ),
            patch("sys.stdout", new=io.StringIO()),
        ):
            exit_code = main()

        self.assertEqual(exit_code, 0)
        mock_client.return_value.upload_file.assert_called_once_with(Path("ROM.zip"), "P661N/16/vanilla", overwrite=False)

    @patch("uploader.sourceforge_cli.SourceForgeClient")
    def test_list_flag_prints_entries(self, mock_client) -> None:
        mock_client.return_value.list_remote.return_value = ["entry-a", "entry-b"]

        with patch("sys.stdout", new=io.StringIO()) as stdout:
            exit_code = main([
                "list",
                "--username", "user",
                "--project", "infinity-x",
                "--remote-dir", "P661N/16/vanilla",
            ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().splitlines(), ["entry-a", "entry-b"])
        mock_client.return_value.list_remote.assert_called_once_with("P661N/16/vanilla")

    @patch("uploader.sourceforge_cli.SourceForgeClient")
    def test_list_without_remote_dir_lists_project_root(self, mock_client) -> None:
        mock_client.return_value.list_remote.return_value = ["root-entry"]

        with patch("sys.stdout", new=io.StringIO()) as stdout:
            exit_code = main([
                "list",
                "--username", "user",
                "--project", "infinity-x",
            ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().splitlines(), ["root-entry"])
        mock_client.return_value.list_remote.assert_called_once_with("")

    @patch("uploader.sourceforge_cli.SourceForgeClient")
    def test_list_accepts_remote_dir_as_positional_argument(self, mock_client) -> None:
        mock_client.return_value.list_remote.return_value = ["release-entry"]

        with patch("sys.stdout", new=io.StringIO()) as stdout:
            exit_code = main([
                "list",
                "release",
                "--username", "user",
                "--project", "rdndds-release",
            ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().splitlines(), ["release-entry"])
        mock_client.return_value.list_remote.assert_called_once_with("release")

    @patch("uploader.sourceforge_cli.SourceForgeClient")
    def test_rename_flag_uses_to_path(self, mock_client) -> None:
        with patch("sys.stdout", new=io.StringIO()):
            exit_code = main([
                "rename",
                "old.zip",
                "--username", "user",
                "--project", "infinity-x",
                "--to", "new.zip",
            ])

        self.assertEqual(exit_code, 0)
        mock_client.return_value.rename_remote.assert_called_once_with("old.zip", "new.zip")

    @patch("uploader.sourceforge_cli.SourceForgeClient")
    def test_rename_accepts_target_as_positional_argument(self, mock_client) -> None:
        with patch("sys.stdout", new=io.StringIO()):
            exit_code = main([
                "rename",
                "old.zip",
                "new.zip",
                "--username", "user",
                "--project", "infinity-x",
            ])

        self.assertEqual(exit_code, 0)
        mock_client.return_value.rename_remote.assert_called_once_with("old.zip", "new.zip")

    @patch("uploader.sourceforge_cli.SourceForgeClient")
    def test_delete_flag_requires_confirm_and_calls_client(self, mock_client) -> None:
        with patch("sys.stdout", new=io.StringIO()):
            exit_code = main([
                "delete",
                "old.zip",
                "--username", "user",
                "--project", "infinity-x",
                "--confirm",
            ])

        self.assertEqual(exit_code, 0)
        mock_client.return_value.delete_remote.assert_called_once_with("old.zip", confirm=True)

    @patch("uploader.sourceforge_cli.SourceForgeClient")
    def test_link_flag_prints_url(self, mock_client) -> None:
        with patch("sys.stdout", new=io.StringIO()) as stdout:
            exit_code = main([
                "link",
                "P661N/16/vanilla/ROM.zip",
                "--username", "user",
                "--project", "infinity-x",
            ])

        self.assertEqual(exit_code, 0)
        self.assertIn("https://sourceforge.net/projects/infinity-x/files/P661N/16/vanilla/ROM.zip/download", stdout.getvalue())

    @patch("uploader.sourceforge_cli.resolve_profile", return_value=SourceForgeProfile())
    def test_missing_credentials_for_action_mode_errors(self, mock_resolve) -> None:
        with patch("sys.stdout", new=io.StringIO()) as stdout:
            exit_code = main([
                "upload",
                "ROM.zip",
                "--remote-dir", "P661N/16/vanilla",
                "--no-telegram",
            ])

        self.assertEqual(exit_code, 2)
        self.assertIn("--username and --project are required", stdout.getvalue())

    @patch("uploader.sourceforge_cli.send_telegram_message")
    @patch("uploader.sourceforge_cli.AppConfig.from_sources")
    @patch("uploader.sourceforge_cli.SourceForgeClient")
    def test_upload_sends_telegram_with_hash_size_and_remote_path(
        self,
        mock_client,
        mock_config,
        mock_send_telegram,
    ) -> None:
        temp_dir, file_path = self._make_file()
        self.addCleanup(temp_dir.cleanup)
        mock_config.return_value.telegram_bot_token = "token"
        mock_config.return_value.telegram_chat_id = "chat-id"
        mock_client.return_value.upload_file.return_value.url = "https://sourceforge.net/projects/infinity-x/files/P661N/16/vanilla/ROM.zip/download"
        mock_client.return_value.upload_file.return_value.service = "SourceForge"
        mock_client.return_value.upload_file.return_value.success = True
        mock_client.return_value.upload_file.return_value.payload = {
            "remote_path": "P661N/16/vanilla/ROM.zip",
            "size_bytes": 11,
            "sha256": "b94d27b9934d3e08a52e52d7da7dabfadeb8f2d7da7dabfadeb8f2d7da7dabfa",
            "file_type": "application/zip",
            "upload_date": "2024-01-01T12:00:00",
        }

        with patch("sys.stdout", new=io.StringIO()):
            exit_code = main([
                "upload",
                str(file_path),
                "--username", "user",
                "--project", "infinity-x",
                "--remote-dir", "P661N/16/vanilla",
            ])

        self.assertEqual(exit_code, 0)
        mock_send_telegram.assert_called_once()
        self.assertEqual(mock_send_telegram.call_args.args[:2], ("token", "chat-id"))
        self.assertEqual(mock_send_telegram.call_args.kwargs["parse_mode"], "HTML")
        message = mock_send_telegram.call_args.args[2]
        self.assertIn("<b>SourceForge Upload Complete</b>", message)
        self.assertIn("<b>File:</b> <code>ROM.zip</code>", message)
        self.assertIn("<blockquote><b>SourceForge</b> ok</blockquote>", message)
        self.assertIn("<blockquote expandable><b>File Details</b>", message)
        self.assertIn("Type: <code>application/zip</code>", message)
        self.assertIn("Size: <code>11.00 B (11 bytes)</code>", message)
        self.assertIn("SHA256: <code>b94d27b9934d3e08a52e52d7da7dabfadeb8f2d7da7dabfadeb8f2d7da7dabfa</code>", message)
        self.assertIn("Remote path: <code>P661N/16/vanilla/ROM.zip</code>", message)
        self.assertIn("Uploaded: <code>2024-01-01 19:00:00 WIB (UTC+7)</code>", message)
        # Verify reply_markup contains inline keyboard with SourceForge button.
        reply_markup = mock_send_telegram.call_args.kwargs.get("reply_markup")
        self.assertIsNotNone(reply_markup)
        import json
        keyboard = json.loads(reply_markup)
        self.assertIn("inline_keyboard", keyboard)
        self.assertEqual(len(keyboard["inline_keyboard"]), 1)
        self.assertEqual(keyboard["inline_keyboard"][0][0]["text"], "SourceForge")

    @patch("uploader.sourceforge_cli.AppConfig.from_sources")
    @patch("uploader.sourceforge_cli.SourceForgeClient")
    def test_upload_requires_telegram_config_unless_skipped(self, mock_client, mock_config) -> None:
        mock_config.return_value.telegram_bot_token = None
        mock_config.return_value.telegram_chat_id = None

        with patch("sys.stdout", new=io.StringIO()) as stdout:
            exit_code = main([
                "upload",
                "ROM.zip",
                "--username", "user",
                "--project", "infinity-x",
                "--remote-dir", "P661N/16/vanilla",
            ])

        self.assertEqual(exit_code, 2)
        self.assertIn("Telegram is required unless --no-telegram is used.", stdout.getvalue())
        mock_client.assert_not_called()

    def test_unknown_legacy_flag_action_is_rejected(self) -> None:
        with patch("sys.stderr", new=io.StringIO()):
            with self.assertRaises(SystemExit):
                main([
                    "--upload", "ROM.zip",
                    "--remote-dir", "P661N/16/vanilla",
                ])


if __name__ == "__main__":
    unittest.main()
