from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rich.console import Console
from rich.filesize import decimal

from uploader.config import AppConfig
from uploader.notifier import format_telegram_message, send_telegram_message
from uploader.progress import create_progress
from uploader.uploaders import UploadResult, upload_gofile, upload_pixeldrain


console = Console()


def format_speed(bytes_per_second: float) -> str:
    if bytes_per_second <= 0:
        return "-"
    return f"{decimal(int(bytes_per_second))}/s"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload a file to Pixeldrain and GoFile in parallel.",
    )
    parser.add_argument("file", help="Path to the file to upload.")
    parser.add_argument("--pixeldrain-key")
    parser.add_argument("--gofile-key")
    parser.add_argument("--telegram-bot-token")
    parser.add_argument("--telegram-chat-id")
    parser.add_argument("--no-telegram", action="store_true", help="Skip Telegram notification.")
    parser.add_argument("--json", action="store_true", help="Print final results as JSON.")
    return parser.parse_args()


def build_failure_result(service: str, error: Exception) -> UploadResult:
    return UploadResult(service=service, success=False, error=str(error))


def main() -> int:
    args = parse_args()
    file_path = Path(args.file).expanduser().resolve()
    if not file_path.exists() or not file_path.is_file():
        console.print(f"[red]File not found:[/red] {file_path}")
        return 2

    config = AppConfig.from_sources(
        pixeldrain_key=args.pixeldrain_key,
        gofile_key=args.gofile_key,
        telegram_bot_token=args.telegram_bot_token,
        telegram_chat_id=args.telegram_chat_id,
    )

    if not args.no_telegram and (not config.telegram_bot_token or not config.telegram_chat_id):
        console.print("[red]Telegram is required unless --no-telegram is used.[/red]")
        console.print("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID, or pass matching flags.")
        return 2

    progress = create_progress()
    results_by_service: dict[str, UploadResult] = {}
    file_name = file_path.name
    file_size = file_path.stat().st_size

    with progress:
        task_map = {
            "Pixeldrain": progress.add_task(
                "pixeldrain",
                service="Pixeldrain",
                filename=file_name,
                state="preparing",
                speed="-",
                total=file_size,
            ),
            "GoFile": progress.add_task(
                "gofile",
                service="GoFile",
                filename=file_name,
                state="preparing",
                speed="-",
                total=file_size,
            ),
        }
        speed_state = {
            "Pixeldrain": {"started_at": None, "last_speed": "-"},
            "GoFile": {"started_at": None, "last_speed": "-"},
        }

        def make_callback(service: str):
            task_id = task_map[service]

            def callback(completed: int, total: int) -> None:
                now = time.monotonic()
                state = speed_state[service]
                if state["started_at"] is None and completed > 0:
                    state["started_at"] = now
                elapsed = 0.0 if state["started_at"] is None else max(now - state["started_at"], 1e-6)
                speed = completed / elapsed if completed > 0 else 0.0
                state["last_speed"] = format_speed(speed)
                progress.update(
                    task_id,
                    completed=completed,
                    total=total,
                    state="uploading" if completed < total else "finalizing",
                    speed=state["last_speed"],
                )

            return callback

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_map = {
                executor.submit(upload_pixeldrain, file_path, config.pixeldrain_key, make_callback("Pixeldrain")): "Pixeldrain",
                executor.submit(upload_gofile, file_path, config.gofile_key, make_callback("GoFile")): "GoFile",
            }
            for future in as_completed(future_map):
                service = future_map[future]
                task_id = task_map[service]
                try:
                    result = future.result()
                    results_by_service[service] = result
                    progress.update(
                        task_id,
                        completed=progress.tasks[task_id].total or file_size,
                        state="done",
                        speed=speed_state[service]["last_speed"],
                        refresh=True,
                    )
                except Exception as error:
                    results_by_service[service] = build_failure_result(service, error)
                    progress.update(task_id, state="failed", speed="-")
                    progress.stop_task(task_id)

    results = [results_by_service["Pixeldrain"], results_by_service["GoFile"]]

    if args.json:
        console.print(
            json.dumps(
                [
                    {
                        "service": result.service,
                        "success": result.success,
                        "url": result.url,
                        "error": result.error,
                    }
                    for result in results
                ],
                indent=2,
            )
        )
    else:
        console.print(f"\n[bold]File:[/bold] {file_name}")
        for result in results:
            if result.success:
                console.print(f"[green]{result.service}:[/green] {result.url}")
            else:
                console.print(f"[red]{result.service} failed:[/red] {result.error}")

    exit_code = 0 if all(result.success for result in results) else 1

    if not args.no_telegram:
        try:
            send_telegram_message(
                config.telegram_bot_token or "",
                config.telegram_chat_id or "",
                format_telegram_message(file_name, results),
            )
        except Exception as error:
            console.print(f"[red]Telegram notification failed:[/red] {error}")
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
