from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import requests
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor


PIXELDRAIN_API_BASE = "https://pixeldrain.com/api"
GOFILE_API_BASE = "https://api.gofile.io"
VIKINGFILE_API_BASE = "https://vikingfile.com/api"
TEMPSH_API_BASE = "https://temp.sh/upload"
SENDITSH_API_BASE = "https://sendit.sh"
CHUNK_SIZE = 1024 * 256


ProgressCallback = Callable[[int, int], None]


def calculate_file_hash(file_path: Path, algorithm: str = "sha256") -> str:
    """Calculate file hash using specified algorithm."""
    hash_func = hashlib.new(algorithm)
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            hash_func.update(chunk)
    return hash_func.hexdigest()


def format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def guess_file_type(file_path: Path) -> str | None:
    """Guess MIME type from file extension."""
    mime_type, _ = mimetypes.guess_type(file_path.name)
    return mime_type


class UploadCancelledError(Exception):
    pass


@dataclass(slots=True)
class UploadResult:
    service: str
    success: bool
    url: str | None = None
    payload: dict | None = None
    error: str | None = None
    file_hash: str | None = None
    file_size: int | None = None
    upload_date: str | None = None
    file_type: str | None = None


class ProgressFile:
    def __init__(
        self,
        file_path: Path,
        callback: ProgressCallback,
        cancelled: Callable[[], bool],
    ) -> None:
        self._fh = file_path.open("rb")
        self.callback = callback
        self.cancelled = cancelled
        self.size = file_path.stat().st_size
        self.sent = 0

    def __len__(self) -> int:
        return self.size

    def read(self, size: int = -1) -> bytes:
        if self.cancelled():
            raise UploadCancelledError("Upload cancelled after 30 seconds without progress.")
        chunk = self._fh.read(CHUNK_SIZE if size == -1 else size)
        if not chunk:
            return b""
        self.sent += len(chunk)
        if self.cancelled():
            raise UploadCancelledError("Upload cancelled after 30 seconds without progress.")
        self.callback(self.sent, self.size)
        return chunk

    def close(self) -> None:
        self._fh.close()


def upload_pixeldrain(
    file_path: Path,
    api_key: str,
    callback: ProgressCallback,
    cancelled: Callable[[], bool] | None = None,
) -> UploadResult:
    is_cancelled = cancelled or (lambda: False)
    auth = base64.b64encode(f":{api_key}".encode("utf-8")).decode("ascii")
    file_size = file_path.stat().st_size
    file_hash = calculate_file_hash(file_path)
    file_type = guess_file_type(file_path)
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/octet-stream",
        "Content-Length": str(file_size),
    }
    stream = ProgressFile(file_path, callback, is_cancelled)
    try:
        if is_cancelled():
            raise UploadCancelledError("Upload cancelled after 30 seconds without progress.")
        response = requests.put(
            f"{PIXELDRAIN_API_BASE}/file/{file_path.name}",
            headers=headers,
            data=stream,
            timeout=300,
        )
    finally:
        stream.close()
    response.raise_for_status()
    data = response.json()
    return UploadResult(
        service="Pixeldrain",
        success=True,
        url=f"https://pixeldrain.com/u/{data['id']}",
        payload=data,
        file_hash=file_hash,
        file_size=file_size,
        upload_date=datetime.now().isoformat(),
        file_type=file_type,
    )


def get_gofile_account(api_key: str) -> dict:
    response = requests.get(
        f"{GOFILE_API_BASE}/accounts/website",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"GoFile account lookup failed: {data}")
    return data["data"]


def create_gofile_public_folder(api_key: str, parent_folder_id: str, folder_name: str) -> dict:
    response = requests.post(
        f"{GOFILE_API_BASE}/contents/createFolder",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "parentFolderId": parent_folder_id,
            "folderName": folder_name,
            "public": True,
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"GoFile folder creation failed: {data}")
    return data["data"]


def get_gofile_content(api_key: str, content_id: str) -> dict:
    response = requests.get(
        f"{GOFILE_API_BASE}/contents/{content_id}",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"GoFile content lookup failed: {data}")
    return data["data"]


def get_gofile_folder_url(api_key: str, folder_data: dict) -> str:
    if download_page := folder_data.get("downloadPage") or folder_data.get("link"):
        return download_page
    if code := folder_data.get("code"):
        return f"https://gofile.io/d/{code}"

    folder_id = folder_data.get("id")
    if not folder_id:
        raise RuntimeError("GoFile folder creation succeeded but did not return a folder URL or ID.")

    content = get_gofile_content(api_key, folder_id)
    if download_page := content.get("downloadPage") or content.get("link"):
        return download_page
    if code := content.get("code"):
        return f"https://gofile.io/d/{code}"
    raise RuntimeError("GoFile folder lookup succeeded but did not return a public URL.")


def upload_gofile(
    file_path: Path,
    api_key: str,
    callback: ProgressCallback,
    cancelled: Callable[[], bool] | None = None,
) -> UploadResult:
    is_cancelled = cancelled or (lambda: False)
    if is_cancelled():
        raise UploadCancelledError("Upload cancelled after 30 seconds without progress.")
    file_size = file_path.stat().st_size
    file_hash = calculate_file_hash(file_path)
    file_type = guess_file_type(file_path)
    account = get_gofile_account(api_key)
    folder = create_gofile_public_folder(api_key, account["rootFolder"], file_path.name)
    folder_url = get_gofile_folder_url(api_key, folder)
    with file_path.open("rb") as fh:
        encoder = MultipartEncoder(
            fields={
                "folderId": folder["id"],
                "file": (file_path.name, fh, "application/octet-stream"),
            }
        )

        def guarded_callback(current) -> None:
            if is_cancelled():
                raise UploadCancelledError(
                    "Upload cancelled after 30 seconds without progress."
                )
            callback(current.bytes_read, current.len)

        monitor = MultipartEncoderMonitor(
            encoder,
            guarded_callback,
        )
        response = requests.post(
            "https://upload.gofile.io/uploadfile",
            data=monitor,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": monitor.content_type,
            },
            timeout=300,
        )
    response.raise_for_status()
    data = response.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"GoFile upload failed: {data}")
    return UploadResult(
        service="GoFile",
        success=True,
        url=folder_url,
        payload=data,
        file_hash=file_hash,
        file_size=file_size,
        upload_date=datetime.now().isoformat(),
        file_type=file_type,
    )


def get_vikingfile_server() -> str:
    response = requests.get(f"{VIKINGFILE_API_BASE}/get-server", timeout=30)
    response.raise_for_status()
    data = response.json()
    server = data.get("server")
    if not server:
        raise RuntimeError(f"Vikingfile server lookup failed: {data}")
    return server


def upload_vikingfile(
    file_path: Path,
    user_hash: str,
    callback: ProgressCallback,
    cancelled: Callable[[], bool] | None = None,
) -> UploadResult:
    is_cancelled = cancelled or (lambda: False)
    if is_cancelled():
        raise UploadCancelledError("Upload cancelled after 30 seconds without progress.")

    file_size = file_path.stat().st_size
    file_hash = calculate_file_hash(file_path)
    file_type = guess_file_type(file_path)
    server = get_vikingfile_server()
    with file_path.open("rb") as fh:
        encoder = MultipartEncoder(
            fields={
                "file": (file_path.name, fh, "application/octet-stream"),
                "user": user_hash,
            }
        )

        def guarded_callback(current) -> None:
            if is_cancelled():
                raise UploadCancelledError(
                    "Upload cancelled after 30 seconds without progress."
                )
            callback(current.bytes_read, current.len)

        monitor = MultipartEncoderMonitor(encoder, guarded_callback)
        response = requests.post(
            server,
            data=monitor,
            headers={"Content-Type": monitor.content_type},
            timeout=300,
        )

    response.raise_for_status()
    data = response.json()
    if not data.get("url"):
        raise RuntimeError(f"Vikingfile upload failed: {data}")

    return UploadResult(
        service="Vikingfile",
        success=True,
        url=data["url"],
        payload=data,
        file_hash=file_hash,
        file_size=file_size,
        upload_date=datetime.now().isoformat(),
        file_type=file_type,
    )


def _upload_direct_with_provider(
    file_path: Path,
    endpoint: str,
    provider_name: str,
    callback: ProgressCallback,
    cancelled: Callable[[], bool] | None = None,
) -> str:
    is_cancelled = cancelled or (lambda: False)
    if is_cancelled():
        raise UploadCancelledError("Upload cancelled after 30 seconds without progress.")

    with file_path.open("rb") as fh:
        encoder = MultipartEncoder(
            fields={
                "file": (file_path.name, fh, "application/octet-stream"),
            }
        )

        def guarded_callback(current) -> None:
            if is_cancelled():
                raise UploadCancelledError(
                    "Upload cancelled after 30 seconds without progress."
                )
            callback(current.bytes_read, current.len)

        monitor = MultipartEncoderMonitor(encoder, guarded_callback)
        response = requests.post(
            endpoint,
            data=monitor,
            headers={"Content-Type": monitor.content_type},
            timeout=300,
        )

    response.raise_for_status()
    response_text = response.text.strip()
    if provider_name == "sendit.sh":
        match = re.search(r"https://sendit\.sh/\S+", response_text)
        if not match:
            raise RuntimeError(
                f"sendit.sh upload response did not contain a valid download URL: {response_text}"
            )
        return match.group(0)

    if not response_text or not response_text.startswith("https://temp.sh/"):
        raise RuntimeError(
            f"temp.sh upload response did not contain a valid download URL: {response_text}"
        )
    return response_text


def upload_direct(
    file_path: Path,
    callback: ProgressCallback,
    cancelled: Callable[[], bool] | None = None,
) -> UploadResult:
    is_cancelled = cancelled or (lambda: False)
    file_size = file_path.stat().st_size
    file_hash = calculate_file_hash(file_path)
    file_type = guess_file_type(file_path)
    try:
        download_url = _upload_direct_with_provider(
            file_path,
            SENDITSH_API_BASE,
            "sendit.sh",
            callback,
            cancelled=is_cancelled,
        )
        provider = "sendit.sh"
    except UploadCancelledError:
        raise
    except Exception as sendit_error:
        try:
            download_url = _upload_direct_with_provider(
                file_path,
                TEMPSH_API_BASE,
                "temp.sh",
                callback,
                cancelled=is_cancelled,
            )
            provider = "temp.sh"
        except UploadCancelledError:
            raise
        except Exception as temp_error:
            raise RuntimeError(
                f"direct upload failed via sendit.sh ({sendit_error}) and temp.sh ({temp_error})"
            ) from temp_error

    return UploadResult(
        service="Direct",
        success=True,
        url=download_url,
        payload={"provider": provider, "url": download_url},
        file_hash=file_hash,
        file_size=file_size,
        upload_date=datetime.now().isoformat(),
        file_type=file_type,
    )
