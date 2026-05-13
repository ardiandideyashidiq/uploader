from __future__ import annotations

import json
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import requests

from uploader.uploaders import UploadResult, format_file_size

WIB = ZoneInfo("Asia/Jakarta")


def _format_upload_date(upload_date: str | None) -> str | None:
    """Convert ISO upload date to WIB (UTC+7) formatted string."""
    if not upload_date:
        return None
    try:
        dt = datetime.fromisoformat(upload_date)
        # Treat naive datetimes as UTC.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        dt_wib = dt.astimezone(WIB)
        return dt_wib.strftime("%Y-%m-%d %H:%M:%S WIB (UTC+7)")
    except ValueError:
        return None


def build_download_keyboard(results: list[UploadResult]) -> str | None:
    """Build Telegram InlineKeyboardMarkup JSON with URL buttons for each successful upload."""
    buttons = []
    for result in results:
        if result.success and result.url:
            buttons.append([{"text": result.service, "url": result.url}])
    if not buttons:
        return None
    return json.dumps({"inline_keyboard": buttons})


def format_telegram_message(filename: str, results: list[UploadResult]) -> str:
    lines = ["<b>Upload Complete</b>", ""]

    # Get file metadata from the first successful result.
    file_size = None
    file_hash = None
    upload_date = None
    file_type = None

    for result in results:
        if result.success:
            file_size = result.file_size
            file_hash = result.file_hash
            upload_date = result.upload_date
            file_type = result.file_type
            break

    # Filename on top.
    lines.append(f"<b>File:</b> <code>{escape(filename)}</code>")

    # Service status in a blockquote (links are buttons below the message).
    # Only show successful uploads; failures are visible in the CLI output.
    successful = [r for r in results if r.success and r.url]
    if successful:
        lines.append("<blockquote><b>Services</b>")
        for result in successful:
            lines.append(f"• <b>{escape(result.service)}:</b> ok")
        lines.append("</blockquote>")

    # File details in an expandable blockquote (accordion).
    lines.append("<blockquote expandable><b>File Details</b>")
    if file_type:
        lines.append(f"Type: <code>{escape(file_type)}</code>")
    if file_size:
        lines.append(
            f"Size: <code>{escape(format_file_size(file_size))} ({file_size} bytes)</code>"
        )
    if file_hash:
        lines.append(f"SHA256: <code>{escape(file_hash)}</code>")
    formatted_date = _format_upload_date(upload_date)
    if formatted_date:
        lines.append(f"Uploaded: <code>{escape(formatted_date)}</code>")
    lines.append("</blockquote>")

    return "\n".join(lines)


def send_telegram_message(
    bot_token: str,
    chat_id: str,
    message: str,
    parse_mode: str = "HTML",
    reply_markup: str | None = None,
) -> None:
    data = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": parse_mode,
        "disable_web_page_preview": "true",
    }
    if reply_markup:
        data["reply_markup"] = reply_markup
    response = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=data,
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        error_description = payload.get("description", "Unknown error")
        error_parameters = payload.get("parameters", {})
        raise RuntimeError(f"Telegram API error: {error_description} - Parameters: {error_parameters}")