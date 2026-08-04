from __future__ import annotations

import argparse
import json
import sys
import time
import threading
from pathlib import Path

from InquirerPy import inquirer
from rich.console import Console
from rich.filesize import decimal
from rich.status import Status

from uploader.config import AppConfig, get_config_path
from uploader.notifier import build_download_keyboard, format_telegram_message, send_telegram_message
from uploader.progress import create_progress
from uploader.retry import retry_upload
from uploader.sourceforge_cli import main as sourceforge_main
from uploader.uploaders import (
    UploadCancelledError,
    UploadResult,
    upload_direct,
    upload_gofile,
    upload_pixeldrain,
    upload_vikingfile,
)


console = Console()
STALL_TIMEOUT_SECONDS = 30
POLL_INTERVAL_SECONDS = 1


def format_speed(bytes_per_second: float) -> str:
    if bytes_per_second <= 0:
        return "-"
    return f"{decimal(int(bytes_per_second))}/s"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload a file to supported services.",
    )
    parser.add_argument("file", nargs="?", default=None, help="Path to the file to upload.")
    parser.add_argument(
        "--config",
        help="Path to config file (default: ~/.config/uploader/config)",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Run interactive setup to save optional credentials.",
    )
    parser.add_argument("--pixeldrain-key")
    parser.add_argument("--gofile-key")
    parser.add_argument("--vikingfile-user")
    parser.add_argument("--telegram-bot-token")
    parser.add_argument("--telegram-chat-id")
    parser.add_argument(
        "-s",
        "--single",
        action="store_true",
        help="Select a single upload destination interactively.",
    )
    parser.add_argument(
        "-d",
        "--direct",
        action="store_true",
        help="Upload to sendit.sh.",
    )
    parser.add_argument(
        "--no-telegram", action="store_true", help="Skip Telegram notification."
    )
    parser.add_argument(
        "--json", action="store_true", help="Print final results as JSON."
    )
    return parser.parse_args(argv)


def run_setup(config_path: Path) -> None:
    import yaml

    config_path.parent.mkdir(parents=True, exist_ok=True)

    console.print("[bold]Uploader Setup[/bold]")
    console.print("Paste optional config in YAML format:\n")

    console.print("[dim]# Optional:")
    console.print("[dim]pixeldrain_key: YOUR_PIXELDRAIN_KEY")
    console.print("[dim]gofile_key: YOUR_GOFILE_KEY")
    console.print("[dim]vikingfile_user: YOUR_VIKINGFILE_USER")
    console.print("[dim]telegram_bot_token: YOUR_TOKEN")
    console.print("[dim]telegram_chat_id: YOUR_CHAT_ID")
    console.print("")

    while True:
        yaml_input = inquirer.text(
            message="Paste config:",
            multiline=True,
        ).execute()

        try:
            config_data = yaml.safe_load(yaml_input) or {}
        except yaml.YAMLError as e:
            console.print(f"[red]Invalid YAML: {e}[/red]")
            continue

        if not isinstance(config_data, dict):
            console.print("[red]Invalid format: expected YAML object[/red]")
            continue

        config_data = {
            key: config_data.get(key) or None
            for key in (
                "pixeldrain_key",
                "gofile_key",
                "vikingfile_user",
                "telegram_bot_token",
                "telegram_chat_id",
            )
            if config_data.get(key)
        }

        with open(config_path, "w") as f:
            yaml.safe_dump(config_data, f, sort_keys=False)

        console.print(f"[green]Config saved to {config_path}[/green]")
        return


def build_default_services(config: AppConfig) -> list[str]:
    services = ["GoFile", "Vikingfile"]
    if config.pixeldrain_key:
        services.append("Pixeldrain")
    return services


def build_single_service_choices(config: AppConfig) -> list[str]:
    return [*build_default_services(config), "Direct"]


def build_failure_result(service: str, error: Exception) -> UploadResult:
    return UploadResult(service=service, success=False, error=str(error))


def build_cancelled_result(service: str) -> UploadResult:
    return build_failure_result(
        service,
        UploadCancelledError("Upload cancelled after 30 seconds without progress."),
    )


def select_single_service(config: AppConfig) -> str:
    if not sys.stdin.isatty():
        raise RuntimeError("Single upload requires an interactive terminal.")

    choices = build_single_service_choices(config)
    choice = inquirer.select(
        message="Select upload destination:",
        choices=choices,
    ).execute()
    if choice not in set(choices):
        raise RuntimeError("Invalid single upload selection.")
    return choice


def main(argv: list[str] | None = None) -> int:
    try:
        args_list = sys.argv[1:] if argv is None else argv
        if args_list and args_list[0] == "sourceforge":
            return sourceforge_main(args_list[1:])

        args = parse_args(args_list)
        config_path = get_config_path(args.config)

        if args.setup:
            if not sys.stdin.isatty():
                console.print("[red]Setup requires an interactive terminal.[/red]")
                return 1
            console.print("[yellow]Running optional setup...[/yellow]\n")
            run_setup(config_path)
            if args.file is None:
                return 0

        if args.file is None:
            console.print("[red]the following arguments are required: file[/red]")
            return 2

        file_path = Path(args.file).expanduser().resolve()
        if not file_path.exists() or not file_path.is_file():
            console.print(f"[red]File not found:[/red] {file_path}")
            return 2

        config = AppConfig.from_sources(
            config_path=config_path,
            pixeldrain_key=args.pixeldrain_key,
            gofile_key=args.gofile_key,
            vikingfile_user=args.vikingfile_user,
            telegram_bot_token=args.telegram_bot_token,
            telegram_chat_id=args.telegram_chat_id,
        )

        services = build_default_services(config)
        if args.direct:
            services = ["Direct"]
        elif args.single:
            try:
                services = [select_single_service(config)]
            except RuntimeError as error:
                console.print(f"[red]{error}[/red]")
                return 2

        progress = create_progress()
        results_by_service: dict[str, UploadResult] = {}
        result_lock = threading.Lock()
        finished_events: dict[str, threading.Event] = {
            service: threading.Event() for service in services
        }
        cancel_events: dict[str, threading.Event] = {
            service: threading.Event() for service in services
        }
        file_name = file_path.name
        file_size = file_path.stat().st_size

        with progress:
            task_map = {}
            speed_state = {}
            for service in services:
                task_map[service] = progress.add_task(
                    service.lower(),
                    service=service,
                    filename=file_name,
                    state="preparing",
                    speed="-",
                    total=file_size,
                )
                speed_state[service] = {
                    "started_at": time.monotonic(),
                    "last_progress_at": time.monotonic(),
                    "last_speed": "-",
                }

            def store_result(service: str, result: UploadResult) -> bool:
                with result_lock:
                    if service in results_by_service:
                        return False
                    results_by_service[service] = result
                    return True

            def make_callback(service: str):
                task_id = task_map[service]

                def callback(completed: int, total: int) -> None:
                    now = time.monotonic()
                    state = speed_state[service]
                    state["last_progress_at"] = now
                    elapsed = (
                        0.0
                        if state["started_at"] is None
                        else max(now - state["started_at"], 1e-6)
                    )
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

            uploaders = {
                "Pixeldrain": upload_pixeldrain,
                "GoFile": upload_gofile,
                "Vikingfile": upload_vikingfile,
                "Direct": upload_direct,
            }
            uploader_credentials = {
                "Pixeldrain": config.pixeldrain_key,
                "GoFile": config.gofile_key or None,
                "Vikingfile": config.vikingfile_user or "",
                "Direct": None,
            }

            def make_worker(service: str):
                def worker() -> None:
                    try:
                        if service == "Direct":
                            result = retry_upload(
                                lambda service=service: uploaders[service](
                                    file_path,
                                    make_callback(service),
                                    cancelled=cancel_events[service].is_set,
                                )
                            )
                        else:
                            result = retry_upload(
                                lambda service=service: uploaders[service](
                                    file_path,
                                    uploader_credentials[service],
                                    make_callback(service),
                                    cancelled=cancel_events[service].is_set,
                                )
                            )
                    except Exception as error:
                        result = build_failure_result(service, error)

                    if store_result(service, result):
                        finished_events[service].set()

                return worker

            for service in services:
                thread = threading.Thread(
                    target=make_worker(service),
                    name=f"upload-{service.lower()}",
                    daemon=True,
                )
                thread.start()

            active_services = set(services)
            while active_services:
                now = time.monotonic()
                for service in list(active_services):
                    task_id = task_map[service]
                    with result_lock:
                        already_finished = service in results_by_service

                    if (
                        service == "Pixeldrain"
                        and not already_finished
                        and now - speed_state[service]["last_progress_at"] > STALL_TIMEOUT_SECONDS
                    ):
                        cancel_events[service].set()
                        if store_result(service, build_cancelled_result(service)):
                            progress.update(task_id, state="failed", speed="-")
                            progress.stop_task(task_id)
                        active_services.remove(service)
                        continue

                    if finished_events[service].is_set():
                        with result_lock:
                            result = results_by_service[service]
                        progress.update(
                            task_id,
                            completed=progress.tasks[task_id].total or file_size,
                            state="done" if result.success else "failed",
                            speed=speed_state[service]["last_speed"],
                            refresh=True,
                        )
                        if not result.success:
                            progress.stop_task(task_id)
                        active_services.remove(service)

                if active_services:
                    time.sleep(POLL_INTERVAL_SECONDS)

        results = [results_by_service[service] for service in services]

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

        if (
            not args.no_telegram
            and config.telegram_bot_token
            and config.telegram_chat_id
        ):
            try:
                with Status("Sending Telegram notification...", console=console, spinner="dots"):
                    send_telegram_message(
                        config.telegram_bot_token or "",
                        config.telegram_chat_id or "",
                        format_telegram_message(file_name, results),
                        parse_mode="HTML",
                        reply_markup=build_download_keyboard(results),
                    )
                console.print("[green]Telegram notification sent.[/green]")
            except Exception as error:
                console.print(f"[red]Telegram notification failed:[/red] {error}")
                exit_code = 1

        return exit_code
    except KeyboardInterrupt:
        console.print("[red]Cancelled.[/red]")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
