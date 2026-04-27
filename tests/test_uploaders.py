from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from uploader.uploaders import (
    UploadCancelledError,
    upload_gofile,
    upload_pixeldrain,
    upload_vikingfile,
)


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class UploadGoFileTests(unittest.TestCase):
    def _make_file(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temp_dir = tempfile.TemporaryDirectory()
        file_path = Path(temp_dir.name) / "example.txt"
        file_path.write_bytes(b"hello world")
        return temp_dir, file_path

    @patch("uploader.uploaders.requests.post")
    @patch("uploader.uploaders.requests.get")
    def test_upload_gofile_creates_public_folder_and_returns_folder_url(self, mock_get, mock_post) -> None:
        temp_dir, file_path = self._make_file()
        self.addCleanup(temp_dir.cleanup)

        mock_get.return_value = FakeResponse(
            {
                "status": "ok",
                "data": {"rootFolder": "root-folder-id"},
            }
        )
        mock_post.side_effect = [
            FakeResponse(
                {
                    "status": "ok",
                    "data": {"id": "folder-123", "code": "folder-code"},
                }
            ),
            FakeResponse(
                {
                    "status": "ok",
                    "data": {"downloadPage": "https://gofile.io/d/file-page"},
                }
            ),
        ]

        result = upload_gofile(
            file_path,
            "api-key",
            lambda *_: None,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.url, "https://gofile.io/d/folder-code")
        self.assertIsNotNone(result.payload)

        create_folder_call = mock_post.call_args_list[0]
        self.assertEqual(create_folder_call.args[0], "https://api.gofile.io/contents/createFolder")
        self.assertEqual(
            create_folder_call.kwargs["json"],
            {
                "parentFolderId": "root-folder-id",
                "folderName": "example.txt",
                "public": True,
            },
        )

        upload_call = mock_post.call_args_list[1]
        self.assertEqual(upload_call.args[0], "https://upload.gofile.io/uploadfile")
        self.assertEqual(upload_call.kwargs["headers"]["Authorization"], "Bearer api-key")
        self.assertIn("folderId", upload_call.kwargs["data"].encoder.fields)
        self.assertEqual(upload_call.kwargs["data"].encoder.fields["folderId"], "folder-123")

    @patch("uploader.uploaders.requests.post")
    @patch("uploader.uploaders.requests.get")
    def test_upload_gofile_raises_when_folder_creation_fails(self, mock_get, mock_post) -> None:
        temp_dir, file_path = self._make_file()
        self.addCleanup(temp_dir.cleanup)

        mock_get.return_value = FakeResponse(
            {
                "status": "ok",
                "data": {"rootFolder": "root-folder-id"},
            }
        )
        mock_post.return_value = FakeResponse(
            {
                "status": "error",
                "message": "duplicate name",
            }
        )

        with self.assertRaisesRegex(RuntimeError, "GoFile folder creation failed"):
            upload_gofile(file_path, "api-key", lambda *_: None)

    @patch("uploader.uploaders.requests.post")
    @patch("uploader.uploaders.requests.get")
    def test_upload_gofile_raises_when_upload_fails(self, mock_get, mock_post) -> None:
        temp_dir, file_path = self._make_file()
        self.addCleanup(temp_dir.cleanup)

        mock_get.return_value = FakeResponse(
            {
                "status": "ok",
                "data": {"rootFolder": "root-folder-id"},
            }
        )
        mock_post.side_effect = [
            FakeResponse(
                {
                    "status": "ok",
                    "data": {
                        "id": "folder-123",
                        "downloadPage": "https://gofile.io/d/folder-page",
                    },
                }
            ),
            FakeResponse(
                {
                    "status": "error",
                    "message": "upload failed",
                }
            ),
        ]

        with self.assertRaisesRegex(RuntimeError, "GoFile upload failed"):
            upload_gofile(file_path, "api-key", lambda *_: None)

    @patch("uploader.uploaders.requests.put")
    def test_upload_pixeldrain_raises_when_cancelled_before_start(self, mock_put) -> None:
        temp_dir, file_path = self._make_file()
        self.addCleanup(temp_dir.cleanup)

        with self.assertRaisesRegex(
            UploadCancelledError, "Upload cancelled after 30 seconds without progress"
        ):
            upload_pixeldrain(file_path, "api-key", lambda *_: None, cancelled=lambda: True)

        mock_put.assert_not_called()


class UploadVikingfileTests(unittest.TestCase):
    def _make_file(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temp_dir = tempfile.TemporaryDirectory()
        file_path = Path(temp_dir.name) / "example.txt"
        file_path.write_bytes(b"hello world")
        return temp_dir, file_path

    @patch("uploader.uploaders.requests.post")
    @patch("uploader.uploaders.requests.get")
    def test_upload_vikingfile_uploads_file_and_returns_url(self, mock_get, mock_post) -> None:
        temp_dir, file_path = self._make_file()
        self.addCleanup(temp_dir.cleanup)

        mock_get.return_value = FakeResponse({"server": "https://upload.vikingfile.com"})
        mock_post.return_value = FakeResponse(
            {
                "name": "example.txt",
                "size": 11,
                "hash": "TPRSfLvcIu",
                "url": "https://vikingfile.com/f/TPRSfLvcIu",
            }
        )

        result = upload_vikingfile(file_path, "user-hash", lambda *_: None)

        self.assertTrue(result.success)
        self.assertEqual(result.url, "https://vikingfile.com/f/TPRSfLvcIu")
        self.assertIsNotNone(result.payload)
        self.assertEqual(mock_get.call_args.args[0], "https://vikingfile.com/api/get-server")

        upload_call = mock_post.call_args
        self.assertEqual(upload_call.args[0], "https://upload.vikingfile.com")
        self.assertEqual(upload_call.kwargs["data"].encoder.fields["user"], "user-hash")
        self.assertIn("file", upload_call.kwargs["data"].encoder.fields)

    @patch("uploader.uploaders.requests.post")
    @patch("uploader.uploaders.requests.get")
    def test_upload_vikingfile_raises_when_server_lookup_fails(self, mock_get, mock_post) -> None:
        temp_dir, file_path = self._make_file()
        self.addCleanup(temp_dir.cleanup)

        mock_get.return_value = FakeResponse({})

        with self.assertRaisesRegex(RuntimeError, "Vikingfile server lookup failed"):
            upload_vikingfile(file_path, "", lambda *_: None)

        mock_post.assert_not_called()

    @patch("uploader.uploaders.requests.post")
    @patch("uploader.uploaders.requests.get")
    def test_upload_vikingfile_raises_when_upload_response_has_no_url(self, mock_get, mock_post) -> None:
        temp_dir, file_path = self._make_file()
        self.addCleanup(temp_dir.cleanup)

        mock_get.return_value = FakeResponse({"server": "https://upload.vikingfile.com"})
        mock_post.return_value = FakeResponse({"hash": "TPRSfLvcIu"})

        with self.assertRaisesRegex(RuntimeError, "Vikingfile upload failed"):
            upload_vikingfile(file_path, "", lambda *_: None)

    @patch("uploader.uploaders.requests.get")
    @patch("uploader.uploaders.requests.post")
    def test_upload_vikingfile_raises_when_cancelled_before_start(self, mock_post, mock_get) -> None:
        temp_dir, file_path = self._make_file()
        self.addCleanup(temp_dir.cleanup)

        with self.assertRaisesRegex(
            UploadCancelledError, "Upload cancelled after 30 seconds without progress"
        ):
            upload_vikingfile(file_path, "", lambda *_: None, cancelled=lambda: True)

        mock_get.assert_not_called()
        mock_post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
