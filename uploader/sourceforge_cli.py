from __future__ import annotations

import argparse
from datetime import datetime
from html import escape
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from rich.console import Console
from rich.filesize import decimal

from InquirerPy import inquirer

from uploader.config import AppConfig
from uploader.notifier import build_download_keyboard, send_telegram_message
from uploader.sourceforge import (
    SourceForgeClient,
    SourceForgeConfig,
    SourceForgeError,
    generate_download_url,
)
from uploader.sourceforge_profile import SourceForgeProfile, get_profile_path, load_profile, resolve_profile, save_profile
from uploader.uploaders import format_file_size

WIB = ZoneInfo("Asia/Jakarta")


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--username")
    parser.add_argument("--project")
    parser.add_argument("--remote-root")
    parser.add_argument("--auth-mode", choices=["ssh_key", "interactive_password", "password_helper"], default="ssh_key")
    parser.add_argument("--ssh-key-path")
    parser.add_argument("--password-helper")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="uploader sourceforge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    upload = subparsers.add_parser("upload", help="Upload a file to SourceForge FRS with rsync.")
    upload.add_argument("path", metavar="REMOTE_DIR")
    upload.add_argument("file", nargs="?", metavar="FILE")
    _add_common_options(upload)
    upload.add_argument("--remote-dir")
    upload.add_argument("--overwrite", action="store_true")
    upload.add_argument("--telegram-bot-token")
    upload.add_argument("--telegram-chat-id")
    upload.add_argument("--no-telegram", action="store_true", help="Skip Telegram notification.")

    list_parser = subparsers.add_parser("list", help="List files in a remote SourceForge directory.")
    list_parser.add_argument("remote_dir_arg", nargs="?")
    _add_common_options(list_parser)
    list_parser.add_argument("--remote-dir")

    rename = subparsers.add_parser("rename", help="Rename or move a remote SourceForge path.")
    rename.add_argument("source")
    rename.add_argument("target", nargs="?")
    _add_common_options(rename)
    rename.add_argument("--to")

    delete = subparsers.add_parser("delete", help="Delete a remote SourceForge file.")
    delete.add_argument("path")
    _add_common_options(delete)
    delete.add_argument("--confirm", action="store_true", required=True)

    link = subparsers.add_parser("link", help="Print the public SourceForge download URL for a remote file.")
    link.add_argument("path")
    _add_common_options(link)

    setup = subparsers.add_parser("setup", help="Interactively create/update SourceForge profile.")
    _add_common_options(setup)

    return parser


def _build_config(profile: SourceForgeProfile) -> SourceForgeConfig:
    if not profile.username or not profile.project:
        raise SourceForgeError("--username and --project are required for non-interactive commands.")
    return SourceForgeConfig(
        username=profile.username,
        project=profile.project,
        remote_root=profile.remote_root,
        auth_mode=profile.auth_mode or "ssh_key",
        ssh_key_path=profile.ssh_key_path,
        password_helper=profile.password_helper,
    )


def _build_seed_profile(args: argparse.Namespace) -> SourceForgeProfile:
    return SourceForgeProfile(
        username=args.username,
        project=args.project,
        remote_root=args.remote_root,
        auth_mode=args.auth_mode,
        ssh_key_path=args.ssh_key_path,
        password_helper=args.password_helper,
    )


def _format_size(size_bytes: int) -> str:
    if size_bytes == 1:
        return "1 B"
    if size_bytes < 1000:
        return f"{size_bytes} B"
    return decimal(size_bytes)


def format_sourceforge_telegram_message(filename: str, result_url: str, payload: dict[str, object]) -> str:
    size_bytes = int(payload.get("size_bytes", 0))
    sha256 = str(payload.get("sha256", ""))
    remote_path = str(payload.get("remote_path", ""))
    file_type = payload.get("file_type")
    upload_date = payload.get("upload_date")

    lines = [
        "<b>SourceForge Upload Complete</b>",
        "",
        f"<b>File:</b> <code>{escape(filename)}</code>",
        "<blockquote><b>SourceForge</b> ok</blockquote>",
        "<blockquote expandable><b>File Details</b>",
    ]
    if file_type:
        lines.append(f"Type: <code>{escape(str(file_type))}</code>")
    lines.append(f"Size: <code>{escape(format_file_size(size_bytes))} ({size_bytes} bytes)</code>")
    lines.append(f"SHA256: <code>{escape(sha256)}</code>")
    lines.append(f"Remote path: <code>{escape(remote_path)}</code>")
    if upload_date:
        try:
            dt = datetime.fromisoformat(str(upload_date))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("UTC"))
            dt_wib = dt.astimezone(WIB)
            formatted = dt_wib.strftime("%Y-%m-%d %H:%M:%S WIB (UTC+7)")
            lines.append(f"Uploaded: <code>{escape(formatted)}</code>")
        except ValueError:
            pass
    lines.append("</blockquote>")
    return "\n".join(lines)


def _prompt_profile(profile: SourceForgeProfile, console: Console) -> SourceForgeProfile | None:
    username = inquirer.text(
        message="SourceForge username:",
        default=profile.username or "",
    ).execute()

    if not username:
        console.print("[red]Username is required.[/red]")
        return None

    project = inquirer.text(
        message="SourceForge project:",
        default=profile.project or "",
    ).execute()

    if not project:
        console.print("[red]Project is required.[/red]")
        return None

    default_remote_root = f"/home/frs/project/{project}" if project else ""
    remote_root = inquirer.text(
        message="Remote root (optional):",
        default=profile.remote_root or default_remote_root,
    ).execute()

    auth_mode = inquirer.select(
        message="Authentication mode:",
        choices=[
            {"name": "SSH key", "value": "ssh_key"},
            {"name": "Interactive password", "value": "interactive_password"},
            {"name": "Password helper", "value": "password_helper"},
        ],
        default=profile.auth_mode or "ssh_key",
    ).execute()

    ssh_key_path: str | None = None
    password_helper: str | None = None
    if auth_mode == "ssh_key":
        ssh_key_path = inquirer.text(
            message="SSH key path (optional):",
            default=profile.ssh_key_path or "",
        ).execute() or None
    elif auth_mode == "password_helper":
        password_helper = inquirer.text(
            message="Password helper command:",
            default=profile.password_helper or "",
        ).execute() or None

    return SourceForgeProfile(
        username=username,
        project=project,
        remote_root=remote_root or None,
        auth_mode=auth_mode,
        ssh_key_path=ssh_key_path,
        password_helper=password_helper,
    )


def run_setup(profile: SourceForgeProfile) -> None:
    console = Console()
    console.print("[bold]SourceForge Profile Setup[/bold]")
    console.print("Press Enter to accept default values shown in brackets.\n")

    new_profile = _prompt_profile(profile, console)
    if new_profile is None:
        return

    while True:
        console.print("[yellow]Verifying connection...[/yellow]")
        config = _build_config(new_profile)
        client = SourceForgeClient(config)
        try:
            client.list_remote("")
            console.print("[green]Connection successful![/green]")
            save_profile(new_profile)
            console.print(f"[green]Profile saved to {get_profile_path()}[/green]")
            return
        except SourceForgeError as error:
            console.print(f"[red]Connection failed: {error}[/red]")
            action = inquirer.select(
                message="What would you like to do?",
                choices=[
                    {"name": "Retry", "value": "retry"},
                    {"name": "Edit credentials", "value": "edit"},
                    {"name": "Save anyway (skip check)", "value": "save"},
                    {"name": "Cancel", "value": "cancel"},
                ],
            ).execute()
            if action == "save":
                save_profile(new_profile)
                console.print(f"[green]Profile saved to {get_profile_path()}[/green]")
                return
            if action == "cancel":
                console.print("[yellow]Setup cancelled.[/yellow]")
                return
            if action == "edit":
                new_profile = _prompt_profile(new_profile, console)
                if new_profile is None:
                    return
                continue


def _load_telegram_config(args: argparse.Namespace) -> AppConfig:
    return AppConfig.from_sources(
        pixeldrain_key=None,
        gofile_key=None,
        vikingfile_user=None,
        telegram_bot_token=args.telegram_bot_token,
        telegram_chat_id=args.telegram_chat_id,
    )


def _resolve_upload_args(args: argparse.Namespace, profile: SourceForgeProfile) -> tuple[Path, str]:
    if args.remote_dir is not None:
        if args.file is None:
            return Path(args.path), args.remote_dir
        return Path(args.file), args.remote_dir
    if args.file is not None:
        return Path(args.file), args.path
    candidate = Path(args.path)
    if candidate.exists():
        remote_dir = profile.last_remote_dir or ""
        return candidate, remote_dir
    raise SourceForgeError("upload requires REMOTE_DIR and FILE, or FILE with --remote-dir.")


def _resolve_rename_target(args: argparse.Namespace) -> str:
    if args.to:
        return args.to
    if args.target:
        return args.target
    raise SourceForgeError("rename requires a target path.")


def main(argv: list[str] | None = None) -> int:
    args_list = sys.argv[1:] if argv is None else list(argv)
    parser = build_parser()
    if not args_list:
        parser.print_help()
        return 0
    args = parser.parse_args(args_list)
    seed_profile = _build_seed_profile(args)

    resolved_profile = resolve_profile(cli_profile=seed_profile)

    if args.command == "setup":
        run_setup(resolved_profile)
        return 0

    try:
        if args.command == "link":
            if not resolved_profile.project:
                raise SourceForgeError("--project is required for link.")
            print(generate_download_url(resolved_profile.project, args.path))
            return 0

        telegram_config = None
        if args.command == "upload" and not args.no_telegram:
            telegram_config = _load_telegram_config(args)
            if not telegram_config.telegram_bot_token or not telegram_config.telegram_chat_id:
                raise SourceForgeError("Telegram is required unless --no-telegram is used.")

        config = _build_config(resolved_profile)
        client = SourceForgeClient(config)

        if args.command == "upload":
            local_file, remote_dir = _resolve_upload_args(args, resolved_profile)
            result = client.upload_file(local_file, remote_dir, overwrite=args.overwrite)
            print(result.url)
            if remote_dir:
                stored = load_profile()
                if stored:
                    stored.last_remote_dir = remote_dir
                    save_profile(stored)
            if telegram_config is not None:
                try:
                    send_telegram_message(
                        telegram_config.telegram_bot_token or "",
                        telegram_config.telegram_chat_id or "",
                        format_sourceforge_telegram_message(local_file.name, result.url or "", result.payload or {}),
                        parse_mode="HTML",
                        reply_markup=build_download_keyboard([result]),
                    )
                except Exception as error:
                    print(f"Telegram notification failed: {error}")
                    return 1
        elif args.command == "list":
            remote_dir = args.remote_dir if args.remote_dir is not None else (args.remote_dir_arg or "")
            for line in client.list_remote(remote_dir):
                print(line)
        elif args.command == "rename":
            client.rename_remote(args.source, _resolve_rename_target(args))
        elif args.command == "delete":
            client.delete_remote(args.path, confirm=True)
        return 0
    except SourceForgeError as error:
        print(error)
        return 2
