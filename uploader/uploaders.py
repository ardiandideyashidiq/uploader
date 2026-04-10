from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor


PIXELDRAIN_API_BASE = "https://pixeldrain.com/api"
GOFILE_API_BASE = "https://api.gofile.io"
CHUNK_SIZE = 1024 * 256


ProgressCallback = Callable[[int, int], None]


@dataclass(slots=True)
class UploadResult:
    service: str
    success: bool
    url: str | None = None
    payload: dict | None = None
    error: str | None = None


class ProgressFile:
    def __init__(self, file_path: Path, callback: ProgressCallback) -> None:
        self._fh = file_path.open("rb")
        self.callback = callback
        self.size = file_path.stat().st_size
        self.sent = 0

    def __len__(self) -> int:
        return self.size

    def read(self, size: int = -1) -> bytes:
        chunk = self._fh.read(CHUNK_SIZE if size == -1 else size)
        if not chunk:
            return b""
        self.sent += len(chunk)
        self.callback(self.sent, self.size)
        return chunk

    def close(self) -> None:
        self._fh.close()


def upload_pixeldrain(file_path: Path, api_key: str, callback: ProgressCallback) -> UploadResult:
    auth = base64.b64encode(f":{api_key}".encode("utf-8")).decode("ascii")
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/octet-stream",
        "Content-Length": str(file_path.stat().st_size),
    }
    stream = ProgressFile(file_path, callback)
    try:
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


def get_gofile_server() -> str:
    response = requests.get(f"{GOFILE_API_BASE}/servers", timeout=30)
    response.raise_for_status()
    data = response.json()
    if data.get("status") != "ok" or not data["data"].get("servers"):
        raise RuntimeError(f"GoFile server lookup failed: {data}")
    return data["data"]["servers"][0]["name"]


def upload_gofile(file_path: Path, api_key: str, callback: ProgressCallback) -> UploadResult:
    account = get_gofile_account(api_key)
    server = get_gofile_server()
    with file_path.open("rb") as fh:
        encoder = MultipartEncoder(
            fields={
                "token": api_key,
                "folderId": account["rootFolder"],
                "file": (file_path.name, fh, "application/octet-stream"),
            }
        )
        monitor = MultipartEncoderMonitor(
            encoder,
            lambda current: callback(current.bytes_read, current.len),
        )
        response = requests.post(
            f"https://{server}.gofile.io/uploadfile",
            data=monitor,
            headers={"Content-Type": monitor.content_type},
            timeout=300,
        )
    response.raise_for_status()
    data = response.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"GoFile upload failed: {data}")
    return UploadResult(
        service="GoFile",
        success=True,
        url=data["data"]["downloadPage"],
        payload=data,
    )
