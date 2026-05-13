from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import subprocess
from unittest.mock import patch

from uploader.sourceforge import (
    SourceForgeClient,
    SourceForgeConfig,
    SourceForgeError,
    generate_download_url,
    normalize_remote_dir,
    normalize_remote_path,
    validate_filename,
)


class SourceForgeValidationTests(unittest.TestCase):
    def test_generate_download_url(self) -> None:
        self.assertEqual(
            generate_download_url("infinity-x", "P661N/16/vanilla/ROM zip.zip"),
            "https://sourceforge.net/projects/infinity-x/files/P661N/16/vanilla/ROM%20zip.zip/download",
        )

    def test_rejects_path_traversal(self) -> None:
        with self.assertRaisesRegex(SourceForgeError, "path traversal"):
            normalize_remote_dir("../secret")

    def test_rejects_absolute_paths(self) -> None:
        with self.assertRaisesRegex(SourceForgeError, "relative"):
            normalize_remote_path("/secret")

    def test_rejects_bad_filename(self) -> None:
        with self.assertRaisesRegex(SourceForgeError, "Invalid SourceForge path segment"):
            validate_filename("ROM:bad.zip")


class SourceForgeCommandTests(unittest.TestCase):
    def _make_file(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temp_dir = tempfile.TemporaryDirectory()
        file_path = Path(temp_dir.name) / "ROM.zip"
        file_path.write_bytes(b"hello world")
        return temp_dir, file_path

    @patch.object(SourceForgeClient, "_run_sftp_batch")
    def test_ensure_remote_dir_batches_mkdirs_when_target_is_missing(self, mock_sftp) -> None:
        mock_sftp.side_effect = [
            SourceForgeError("SFTP command failed: Couldn't stat remote file"),
            None,
        ]
        client = SourceForgeClient(SourceForgeConfig(username="user", project="infinity-x"))

        client.ensure_remote_dir("P661N/16/vanilla")

        self.assertEqual(mock_sftp.call_count, 2)
        self.assertEqual(mock_sftp.call_args_list[0].args[0], "cd /home/frs/project/infinity-x/P661N/16/vanilla\n")
        mkdir_batch = mock_sftp.call_args_list[1].args[0]
        self.assertIn("cd /home/frs/project/infinity-x", mkdir_batch)
        self.assertIn("-mkdir P661N", mkdir_batch)
        self.assertIn("-mkdir P661N/16/vanilla", mkdir_batch)

    @patch.object(SourceForgeClient, "_run_sftp_batch")
    def test_ensure_remote_dir_skips_mkdir_when_target_exists(self, mock_sftp) -> None:
        client = SourceForgeClient(SourceForgeConfig(username="user", project="infinity-x"))

        client.ensure_remote_dir("P661N/16/vanilla")

        mock_sftp.assert_called_once_with("cd /home/frs/project/infinity-x/P661N/16/vanilla\n")

    @patch("uploader.sourceforge.subprocess.run")
    def test_sftp_batch_is_quiet_and_uses_error_loglevel(self, mock_run) -> None:
        client = SourceForgeClient(SourceForgeConfig(username="user", project="infinity-x"))

        client._run_sftp_batch("ls -l\n")

        command = mock_run.call_args.args[0]
        self.assertEqual(command[:3], ["sftp", "-oLogLevel=ERROR", "-b"])
        self.assertEqual(command[-1], "user@frs.sourceforge.net")
        self.assertTrue(mock_run.call_args.kwargs["capture_output"])
        self.assertEqual(mock_run.call_args.kwargs["input"], "ls -l\n")

    @patch.object(SourceForgeClient, "_run_command")
    def test_upload_uses_rsync_directly_to_final_path(self, mock_run_command) -> None:
        temp_dir, file_path = self._make_file()
        self.addCleanup(temp_dir.cleanup)
        client = SourceForgeClient(SourceForgeConfig(username="user", project="infinity-x"))

        result = client.upload_file(file_path, "P661N/16/vanilla", overwrite=False)

        self.assertTrue(result.success)
        self.assertEqual(result.url, "https://sourceforge.net/projects/infinity-x/files/P661N/16/vanilla/ROM.zip/download")
        self.assertEqual(result.payload["size_bytes"], 11)
        self.assertEqual(result.payload["sha256"], "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9")
        rsync_command = mock_run_command.call_args.args[0]
        self.assertEqual(rsync_command[0:4], ["rsync", "-avP", "--partial", "--progress"])
        self.assertIn("P661N/16/vanilla/ROM.zip", rsync_command[-1])
        self.assertNotIn(".uploading", rsync_command[-1])

    @patch.object(SourceForgeClient, "ensure_remote_dir")
    @patch.object(SourceForgeClient, "_run_command")
    def test_upload_creates_remote_dir_and_retries_when_rsync_reports_missing_dir(self, mock_run_command, mock_ensure_dir) -> None:
        temp_dir, file_path = self._make_file()
        self.addCleanup(temp_dir.cleanup)
        client = SourceForgeClient(SourceForgeConfig(username="user", project="infinity-x"))
        mock_run_command.side_effect = [
            subprocess.CalledProcessError(
                11,
                ["rsync"],
                output="",
                stderr='rsync: change_dir#3 "/home/frs/project/infinity-x/P661N/16/vanilla" failed: No such file or directory (2)',
            ),
            None,
        ]

        result = client.upload_file(file_path, "P661N/16/vanilla")

        self.assertTrue(result.success)
        self.assertEqual(mock_run_command.call_count, 2)
        mock_ensure_dir.assert_called_once_with("P661N/16/vanilla")

    @patch.object(SourceForgeClient, "ensure_remote_dir")
    @patch.object(SourceForgeClient, "_run_command")
    def test_upload_does_not_use_sftp_fallback_for_other_rsync_failures(self, mock_run_command, mock_ensure_dir) -> None:
        temp_dir, file_path = self._make_file()
        self.addCleanup(temp_dir.cleanup)
        client = SourceForgeClient(SourceForgeConfig(username="user", project="infinity-x"))
        mock_run_command.side_effect = subprocess.CalledProcessError(
            12,
            ["rsync"],
            output="",
            stderr="rsync error: unexplained error",
        )

        with self.assertRaisesRegex(SourceForgeError, "unexplained error"):
            client.upload_file(file_path, "P661N/16/vanilla")

        mock_ensure_dir.assert_not_called()
        mock_run_command.assert_called_once()

    @patch.object(SourceForgeClient, "_run_subprocess")
    def test_list_remote_returns_output_lines(self, mock_run) -> None:
        mock_run.return_value.stdout = "-rw-r--r-- 1 user group 12 Jan 1 00:00 ROM.zip\n"
        client = SourceForgeClient(SourceForgeConfig(username="user", project="infinity-x"))

        lines = client.list_remote("P661N/16/vanilla")

        self.assertEqual(lines, ["-rw-r--r-- 1 user group 12 Jan 1 00:00 ROM.zip"])

    @patch.object(SourceForgeClient, "_run_sftp_batch")
    def test_rename_remote_uses_sftp_rename(self, mock_sftp) -> None:
        client = SourceForgeClient(SourceForgeConfig(username="user", project="infinity-x"))

        client.rename_remote("old.zip", "new.zip")

        self.assertIn(
            "rename /home/frs/project/infinity-x/old.zip /home/frs/project/infinity-x/new.zip",
            mock_sftp.call_args.args[0],
        )

    @patch.object(SourceForgeClient, "_run_sftp_batch")
    def test_delete_remote_requires_confirmation(self, mock_sftp) -> None:
        client = SourceForgeClient(SourceForgeConfig(username="user", project="infinity-x"))

        with self.assertRaisesRegex(SourceForgeError, "confirm=True"):
            client.delete_remote("old.zip")

        client.delete_remote("old.zip", confirm=True)
        self.assertIn("rm /home/frs/project/infinity-x/old.zip", mock_sftp.call_args.args[0])

    @patch("uploader.sourceforge.subprocess.run")
    def test_sftp_batch_failure_raises_sourceforge_error(self, mock_run) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(
            255,
            ["sftp"],
            output="",
            stderr="remote mkdir failed",
        )
        client = SourceForgeClient(SourceForgeConfig(username="user", project="infinity-x"))

        with self.assertRaisesRegex(SourceForgeError, "remote mkdir failed"):
            client._run_sftp_batch("-mkdir release\n")

    @patch.object(SourceForgeClient, "_run_command")
    def test_ssh_key_mode_adds_identity_file(self, mock_run) -> None:
        client = SourceForgeClient(
            SourceForgeConfig(
                username="user",
                project="infinity-x",
                ssh_key_path="/home/user/.ssh/id_ed25519",
            )
        )

        temp_dir, file_path = self._make_file()
        self.addCleanup(temp_dir.cleanup)

        client._run_rsync(file_path, "P661N/16/vanilla/ROM.zip")

        command = mock_run.call_args.args[0]
        self.assertIn("-e", command)
        self.assertEqual(command[command.index("-e") + 1], "ssh -o LogLevel=ERROR -i /home/user/.ssh/id_ed25519")

    @patch.object(SourceForgeClient, "_run_command")
    def test_interactive_password_mode_omits_identity_file(self, mock_run) -> None:
        client = SourceForgeClient(
            SourceForgeConfig(
                username="user",
                project="infinity-x",
                auth_mode="interactive_password",
            )
        )

        temp_dir, file_path = self._make_file()
        self.addCleanup(temp_dir.cleanup)

        client._run_rsync(file_path, "P661N/16/vanilla/ROM.zip")

        command = mock_run.call_args.args[0]
        self.assertIn("-e", command)
        self.assertEqual(command[command.index("-e") + 1], "ssh -o LogLevel=ERROR")

    @patch.object(SourceForgeClient, "_run_with_password_helper")
    @patch.object(SourceForgeClient, "_run_password_helper", return_value="secret")
    def test_password_helper_mode_dispatches_to_pexpect_path(self, mock_helper, mock_run_with_password_helper) -> None:
        client = SourceForgeClient(
            SourceForgeConfig(
                username="user",
                project="infinity-x",
                auth_mode="password_helper",
                password_helper="helper-command",
            )
        )

        client._run_command(["sftp", "-b", "-", "user@frs.sourceforge.net"], input_text="ls -l\n")

        mock_helper.assert_called_once()
        mock_run_with_password_helper.assert_called_once_with(
            ["sftp", "-b", "-", "user@frs.sourceforge.net"],
            "secret",
            input_text="ls -l\n",
        )


if __name__ == "__main__":
    unittest.main()
