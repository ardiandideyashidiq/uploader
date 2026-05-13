from __future__ import annotations

import argparse
from html import escape
from pathlib import Path
import sys

from rich.filesize import decimal

from uploader.config import AppConfig
from uploader.notifier import send_telegram_message
from uploader.sourceforge import (
    SourceForgeClient,
    SourceForgeConfig,
    SourceForgeError,
    generate_download_url,
)
from uploader.sourceforge_profile import SourceForgeProfile, resolve_profile


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
    lines = [
        "<b>SourceForge upload complete</b>",
        f"<b>File:</b> <code>{escape(filename)}</code>",
        f"<b>Size:</b> {_format_size(size_bytes)} ({size_bytes} bytes)",
        f"<b>SHA256:</b> <code>{escape(sha256)}</code>",
        f"<b>Remote path:</b> <code>{escape(remote_path)}</code>",
        f"<b>SourceForge:</b> {escape(result_url)}",
    ]
    return "\n".join(lines)


def _load_telegram_config(args: argparse.Namespace) -> AppConfig:
    return AppConfig.from_sources(
        pixeldrain_key=None,
        gofile_key=None,
        vikingfile_user=None,
        telegram_bot_token=args.telegram_bot_token,
        telegram_chat_id=args.telegram_chat_id,
    )


def _resolve_upload_args(args: argparse.Namespace) -> tuple[Path, str]:
    if args.remote_dir is not None:
        if args.file is None:
            return Path(args.path), args.remote_dir
        return Path(args.file), args.remote_dir
    if args.file is None:
        raise SourceForgeError("upload requires REMOTE_DIR and FILE, or FILE with --remote-dir.")
    return Path(args.file), args.path


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
            local_file, remote_dir = _resolve_upload_args(args)
            result = client.upload_file(local_file, remote_dir, overwrite=args.overwrite)
            print(result.url)
            if telegram_config is not None:
                try:
                    send_telegram_message(
                        telegram_config.telegram_bot_token or "",
                        telegram_config.telegram_chat_id or "",
                        format_sourceforge_telegram_message(local_file.name, result.url or "", result.payload or {}),
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
