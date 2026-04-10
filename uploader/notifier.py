from __future__ import annotations

from html import escape

import requests

from uploader.uploaders import UploadResult


def format_telegram_message(filename: str, results: list[UploadResult]) -> str:
    lines = [f"<b>Upload complete</b>", f"<b>File:</b> <code>{escape(filename)}</code>", ""]
    for result in results:
        if result.success and result.url:
            lines.append(f"<b>{escape(result.service)}:</b> {escape(result.url)}")
        else:
            lines.append(f"<b>{escape(result.service)}:</b> failed")
            if result.error:
                lines.append(f"<i>{escape(result.error)}</i>")
    return "\n".join(lines)


def send_telegram_message(bot_token: str, chat_id: str, message: str) -> None:
    response = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API error: {payload}")
