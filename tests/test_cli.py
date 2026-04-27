from __future__ import annotations

import io
import tempfile
import unittest
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from uploader.cli import main
from uploader.uploaders import UploadCancelledError, UploadResult


class FakeProgress:
    def __init__(self) -> None:
        self.tasks: dict[int, SimpleNamespace] = {}
        self._next_task_id = 0

    def __enter__(self) -> "FakeProgress":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def add_task(self, *_args, **kwargs) -> int:
        task_id = self._next_task_id
        self._next_task_id += 1
        self.tasks[task_id] = SimpleNamespace(total=kwargs.get("total"), stopped=False)
        return task_id

    def update(self, task_id: int, **kwargs) -> None:
        task = self.tasks[task_id]
        if "total" in kwargs:
            task.total = kwargs["total"]
        if kwargs.get("state") == "failed":
            task.failed = True
        if kwargs.get("state") == "done":
            task.done = True

    def stop_task(self, task_id: int) -> None:
        self.tasks[task_id].stopped = True


class CliSingleUploadTests(unittest.TestCase):
    def _make_file(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temp_dir = tempfile.TemporaryDirectory()
        file_path = Path(temp_dir.name) / "example.txt"
        file_path.write_bytes(b"hello world")
        return temp_dir, file_path

    @patch("uploader.cli.send_telegram_message")
    @patch("uploader.cli.upload_vikingfile")
    @patch("uploader.cli.upload_gofile")
    @patch("uploader.cli.upload_pixeldrain")
    @patch("uploader.cli.retry_upload")
    @patch("uploader.cli.create_progress")
    @patch("uploader.cli.AppConfig.from_sources")
    @patch("uploader.cli.inquirer.select")
    def test_single_mode_prompts_for_service_and_uploads_one(
        self,
        mock_select,
        mock_config,
        mock_create_progress,
        mock_retry_upload,
        mock_upload_pixeldrain,
        mock_upload_gofile,
        mock_upload_vikingfile,
        mock_send_telegram,
    ) -> None:
        temp_dir, file_path = self._make_file()
        self.addCleanup(temp_dir.cleanup)

        mock_config.return_value = SimpleNamespace(
            pixeldrain_key="pixeldrain-key",
            gofile_key="gofile-key",
            vikingfile_user="viking-user",
            telegram_bot_token="token",
            telegram_chat_id="chat-id",
        )
        mock_create_progress.return_value = FakeProgress()
        mock_upload_pixeldrain.return_value = UploadResult(
            service="Pixeldrain",
            success=True,
            url="https://pixeldrain.com/u/abc123",
            payload={},
        )
        mock_upload_gofile.return_value = UploadResult(
            service="GoFile",
            success=True,
            url="https://gofile.io/d/xyz789",
            payload={},
        )
        mock_upload_vikingfile.return_value = UploadResult(
            service="Vikingfile",
            success=True,
            url="https://vikingfile.com/f/viking123",
            payload={},
        )
        mock_select.return_value.execute.return_value = "Pixeldrain"
        mock_retry_upload.side_effect = lambda fn, **kwargs: fn()

        with (
            patch(
                "sys.argv", ["uploader", str(file_path), "--no-telegram", "--single"]
            ),
            patch("sys.stdin", io.StringIO()) as mock_stdin,
            patch("uploader.cli.console.print"),
        ):
            mock_stdin.isatty = lambda: True
            exit_code = main()

        self.assertEqual(exit_code, 0)
        mock_select.assert_called_once()
        mock_retry_upload.assert_called_once()
        mock_upload_pixeldrain.assert_called_once()
        mock_upload_gofile.assert_not_called()
        mock_upload_vikingfile.assert_not_called()
        mock_send_telegram.assert_not_called()

    @patch("uploader.cli.console.print")
    def test_single_mode_fails_when_not_interactive(self, mock_print) -> None:
        temp_dir, file_path = self._make_file()
        self.addCleanup(temp_dir.cleanup)

        with (
            patch(
                "sys.argv", ["uploader", str(file_path), "--no-telegram", "--single"]
            ),
            patch("sys.stdin", io.StringIO()) as mock_stdin,
        ):
            mock_stdin.isatty = lambda: False
            exit_code = main()

        self.assertEqual(exit_code, 2)
        mock_print.assert_any_call(
            "[red]Single upload requires an interactive terminal.[/red]"
        )

    @patch("uploader.cli.send_telegram_message")
    @patch("uploader.cli.upload_vikingfile")
    @patch("uploader.cli.upload_gofile")
    @patch("uploader.cli.upload_pixeldrain")
    @patch("uploader.cli.retry_upload")
    @patch("uploader.cli.create_progress")
    @patch("uploader.cli.AppConfig.from_sources")
    @patch("uploader.cli.inquirer.select")
    def test_single_mode_ctrl_c_exits_cleanly(
        self,
        mock_select,
        mock_config,
        mock_create_progress,
        mock_retry_upload,
        mock_upload_pixeldrain,
        mock_upload_gofile,
        mock_upload_vikingfile,
        mock_send_telegram,
    ) -> None:
        temp_dir, file_path = self._make_file()
        self.addCleanup(temp_dir.cleanup)

        mock_config.return_value = SimpleNamespace(
            pixeldrain_key="pixeldrain-key",
            gofile_key="gofile-key",
            vikingfile_user="viking-user",
            telegram_bot_token="token",
            telegram_chat_id="chat-id",
        )
        mock_create_progress.return_value = FakeProgress()
        mock_select.return_value.execute.side_effect = KeyboardInterrupt

        with (
            patch(
                "sys.argv", ["uploader", str(file_path), "--no-telegram", "--single"]
            ),
            patch("sys.stdin", io.StringIO()) as mock_stdin,
            patch("uploader.cli.console.print"),
        ):
            mock_stdin.isatty = lambda: True
            exit_code = main()

        self.assertEqual(exit_code, 130)
        mock_retry_upload.assert_not_called()
        mock_upload_pixeldrain.assert_not_called()
        mock_upload_gofile.assert_not_called()
        mock_upload_vikingfile.assert_not_called()
        mock_send_telegram.assert_not_called()


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        threading.Event().wait(0.0001)


class CliStallTimeoutTests(unittest.TestCase):
    def _make_file(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temp_dir = tempfile.TemporaryDirectory()
        file_path = Path(temp_dir.name) / "example.txt"
        file_path.write_bytes(b"hello world")
        return temp_dir, file_path

    @patch("uploader.cli.send_telegram_message")
    @patch("uploader.cli.create_progress")
    @patch("uploader.cli.AppConfig.from_sources")
    @patch("uploader.cli.upload_vikingfile")
    @patch("uploader.cli.upload_gofile")
    @patch("uploader.cli.upload_pixeldrain")
    @patch("uploader.cli.retry_upload")
    @patch("uploader.cli.time.sleep")
    @patch("uploader.cli.time.monotonic")
    def test_pixeldrain_timeout_keeps_gofile_result(
        self,
        mock_monotonic,
        mock_sleep,
        mock_retry_upload,
        mock_upload_pixeldrain,
        mock_upload_gofile,
        mock_upload_vikingfile,
        mock_config,
        mock_create_progress,
        mock_send_telegram,
    ) -> None:
        temp_dir, file_path = self._make_file()
        self.addCleanup(temp_dir.cleanup)

        clock = FakeClock()
        mock_monotonic.side_effect = clock.monotonic
        mock_sleep.side_effect = clock.sleep

        mock_config.return_value = SimpleNamespace(
            pixeldrain_key="pixeldrain-key",
            gofile_key="gofile-key",
            vikingfile_user="viking-user",
            telegram_bot_token="token",
            telegram_chat_id="chat-id",
        )
        mock_create_progress.return_value = FakeProgress()

        def fake_pixeldrain(file_path, api_key, callback, cancelled=None):
            callback(1, 10)
            while not (cancelled and cancelled()):
                threading.Event().wait(0.001)
            raise UploadCancelledError("Upload cancelled after 30 seconds without progress.")

        def fake_gofile(file_path, api_key, callback, cancelled=None):
            callback(10, 10)
            return UploadResult(
                service="GoFile",
                success=True,
                url="https://gofile.io/d/xyz789",
                payload={},
            )

        def fake_vikingfile(file_path, user_hash, callback, cancelled=None):
            callback(10, 10)
            return UploadResult(
                service="Vikingfile",
                success=True,
                url="https://vikingfile.com/f/viking123",
                payload={},
            )

        mock_upload_pixeldrain.side_effect = fake_pixeldrain
        mock_upload_gofile.side_effect = fake_gofile
        mock_upload_vikingfile.side_effect = fake_vikingfile
        mock_retry_upload.side_effect = lambda fn, **kwargs: fn()

        with (
            patch("sys.argv", ["uploader", str(file_path)]),
            patch("uploader.cli.console.print"),
        ):
            exit_code = main()

        self.assertEqual(exit_code, 1)
        mock_upload_pixeldrain.assert_called_once()
        mock_upload_gofile.assert_called_once()
        mock_upload_vikingfile.assert_called_once()
        mock_send_telegram.assert_called_once()

        message = mock_send_telegram.call_args.args[2]
        self.assertIn("GoFile:", message)
        self.assertIn("https://gofile.io/d/xyz789", message)
        self.assertIn("Vikingfile:", message)
        self.assertIn("https://vikingfile.com/f/viking123", message)
        self.assertIn("<b>Pixeldrain:</b> failed", message)

    @patch("uploader.cli.send_telegram_message")
    @patch("uploader.cli.upload_vikingfile")
    @patch("uploader.cli.upload_gofile")
    @patch("uploader.cli.upload_pixeldrain")
    @patch("uploader.cli.retry_upload")
    @patch("uploader.cli.create_progress")
    @patch("uploader.cli.AppConfig.from_sources")
    @patch("uploader.cli.inquirer.select")
    def test_single_mode_can_select_vikingfile(
        self,
        mock_select,
        mock_config,
        mock_create_progress,
        mock_retry_upload,
        mock_upload_pixeldrain,
        mock_upload_gofile,
        mock_upload_vikingfile,
        mock_send_telegram,
    ) -> None:
        temp_dir, file_path = self._make_file()
        self.addCleanup(temp_dir.cleanup)

        mock_config.return_value = SimpleNamespace(
            pixeldrain_key="pixeldrain-key",
            gofile_key="gofile-key",
            vikingfile_user="viking-user",
            telegram_bot_token="token",
            telegram_chat_id="chat-id",
        )
        mock_create_progress.return_value = FakeProgress()
        mock_upload_vikingfile.return_value = UploadResult(
            service="Vikingfile",
            success=True,
            url="https://vikingfile.com/f/viking123",
            payload={},
        )
        mock_select.return_value.execute.return_value = "Vikingfile"
        mock_retry_upload.side_effect = lambda fn, **kwargs: fn()

        with (
            patch(
                "sys.argv", ["uploader", str(file_path), "--no-telegram", "--single"]
            ),
            patch("sys.stdin", io.StringIO()) as mock_stdin,
            patch("uploader.cli.console.print"),
        ):
            mock_stdin.isatty = lambda: True
            exit_code = main()

        self.assertEqual(exit_code, 0)
        mock_upload_pixeldrain.assert_not_called()
        mock_upload_gofile.assert_not_called()
        mock_upload_vikingfile.assert_called_once()
        self.assertEqual(mock_upload_vikingfile.call_args.args[1], "viking-user")
        mock_send_telegram.assert_not_called()


if __name__ == "__main__":
    unittest.main()
