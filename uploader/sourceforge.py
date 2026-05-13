from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import shlex
import subprocess
from urllib.parse import quote

from uploader.uploaders import UploadResult


SOURCEFORGE_HOST = "frs.sourceforge.net"
SOURCEFORGE_ROOT_PREFIX = "/home/frs/project"
VALID_SEGMENT_RE = re.compile(r"^[A-Za-z0-9 _+\.,=#~@!()\[\]-]+$")
HASH_CHUNK_SIZE = 8 * 1024 * 1024
MISSING_REMOTE_DIR_MARKERS = (
    "No such file or directory",
    "change_dir",
    "mkdir failed",
)


class SourceForgeError(RuntimeError):
    pass


@dataclass(slots=True)
class RemoteEntry:
    name: str
    is_dir: bool
    raw: str


@dataclass(slots=True)
class SourceForgeConfig:
    username: str
    project: str
    remote_root: str | None = None
    host: str = SOURCEFORGE_HOST
    auth_mode: str = "ssh_key"
    ssh_key_path: str | None = None
    password_helper: str | None = None

    @property
    def resolved_remote_root(self) -> str:
        return self.remote_root or f"{SOURCEFORGE_ROOT_PREFIX}/{self.project}"


def _validate_segment(segment: str) -> str:
    if not segment:
        raise SourceForgeError("Remote path segment cannot be empty.")
    if segment in {".", ".."}:
        raise SourceForgeError("Remote path cannot contain path traversal.")
    if segment.startswith((" ", ".")) or segment.endswith(" "):
        raise SourceForgeError(f"Invalid SourceForge path segment: {segment!r}")
    if not VALID_SEGMENT_RE.fullmatch(segment):
        raise SourceForgeError(f"Invalid SourceForge path segment: {segment!r}")
    return segment


def normalize_remote_dir(remote_dir: str) -> str:
    if not remote_dir:
        return ""
    if remote_dir.startswith("/"):
        raise SourceForgeError("Remote paths must be relative to the project root.")
    segments = []
    for raw_segment in remote_dir.split("/"):
        if raw_segment in {"", "."}:
            continue
        segments.append(_validate_segment(raw_segment))
    if any(segment == ".." for segment in segments):
        raise SourceForgeError("Remote path cannot contain path traversal.")
    return "/".join(segments)


def normalize_remote_path(remote_path: str) -> str:
    return normalize_remote_dir(remote_path)


def join_remote_path(parent: str, child: str) -> str:
    parent_normalized = normalize_remote_dir(parent)
    child_normalized = normalize_remote_dir(child)
    if not parent_normalized:
        return child_normalized
    if not child_normalized:
        return parent_normalized
    return f"{parent_normalized}/{child_normalized}"


def parent_remote_path(remote_path: str) -> str:
    normalized = normalize_remote_dir(remote_path)
    if not normalized or "/" not in normalized:
        return ""
    return normalized.rsplit("/", 1)[0]


def validate_filename(filename: str) -> str:
    return _validate_segment(filename)


def generate_download_url(project: str, remote_path: str) -> str:
    normalized = normalize_remote_path(remote_path)
    segments = normalized.split("/") if normalized else []
    encoded = "/".join(quote(segment, safe="") for segment in segments)
    return f"https://sourceforge.net/projects/{quote(project, safe='')}/files/{encoded}/download"


def hash_file(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ssh_command(config: SourceForgeConfig) -> list[str]:
    command = ["ssh", "-o", "LogLevel=ERROR"]
    if config.ssh_key_path:
        command.extend(["-i", config.ssh_key_path])
    return command


def _sftp_command(config: SourceForgeConfig) -> list[str]:
    command = ["sftp", "-oLogLevel=ERROR"]
    if config.ssh_key_path:
        command.extend(["-i", config.ssh_key_path])
    return command


def _subprocess_error_detail(error: subprocess.CalledProcessError) -> str:
    output = "\n".join(
        part.strip()
        for part in (
            getattr(error, "stderr", None) or "",
            getattr(error, "stdout", None) or getattr(error, "output", None) or "",
        )
        if part and part.strip()
    )
    return output or f"exit status {error.returncode}"


def _is_missing_remote_dir_error(message: str) -> bool:
    return any(marker in message for marker in MISSING_REMOTE_DIR_MARKERS)


class SourceForgeClient:
    def __init__(self, config: SourceForgeConfig) -> None:
        self.config = config

    def _remote_dir_abs(self, remote_dir: str) -> str:
        normalized = normalize_remote_dir(remote_dir)
        if not normalized:
            return self.config.resolved_remote_root
        return f"{self.config.resolved_remote_root}/{normalized}"

    def _remote_path_abs(self, remote_path: str) -> str:
        normalized = normalize_remote_path(remote_path)
        return f"{self.config.resolved_remote_root}/{normalized}"

    def _run_subprocess(
        self,
        command: list[str],
        *,
        input_text: str | None = None,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            input=input_text,
            text=True,
            capture_output=capture_output,
            check=True,
        )

    def _run_password_helper(self) -> str:
        if not self.config.password_helper:
            raise SourceForgeError("password_helper auth requires a password helper command.")
        helper_command = shlex.split(self.config.password_helper)
        result = subprocess.run(
            helper_command,
            text=True,
            capture_output=True,
            check=True,
        )
        password = result.stdout.strip()
        if not password:
            raise SourceForgeError("Password helper returned no password.")
        return password

    def _run_with_password_helper(
        self,
        command: list[str],
        password: str,
        input_text: str | None = None,
    ) -> None:
        try:
            import pexpect
        except ImportError as error:  # pragma: no cover - dependency error path
            raise SourceForgeError("password_helper auth requires pexpect.") from error

        child = pexpect.spawn(command[0], command[1:], encoding="utf-8")
        try:
            index = child.expect([r"[Pp]assword:", pexpect.EOF, pexpect.TIMEOUT])
            if index != 0:
                raise SourceForgeError("Password prompt did not appear.")
            child.sendline(password)
            if input_text:
                child.send(input_text)
                child.sendeof()
            child.expect(pexpect.EOF)
            if child.exitstatus not in (0, None):
                raise SourceForgeError(f"Command failed with exit status {child.exitstatus}.")
        finally:
            child.close(force=True)

    def _run_command(self, command: list[str], *, input_text: str | None = None) -> None:
        if self.config.auth_mode == "password_helper":
            password = self._run_password_helper()
            self._run_with_password_helper(command, password, input_text=input_text)
            return
        self._run_subprocess(command, input_text=input_text)

    def _run_sftp_batch(self, input_text: str) -> subprocess.CompletedProcess[str] | None:
        command = [
            *_sftp_command(self.config),
            "-b",
            "-",
            f"{self.config.username}@{self.config.host}",
        ]
        if self.config.auth_mode == "password_helper":
            password = self._run_password_helper()
            self._run_with_password_helper(command, password, input_text=input_text)
            return None
        try:
            return self._run_subprocess(command, input_text=input_text, capture_output=True)
        except subprocess.CalledProcessError as error:
            raise SourceForgeError(f"SFTP command failed: {_subprocess_error_detail(error)}") from error

    def ensure_remote_dir(self, remote_dir: str) -> None:
        normalized = normalize_remote_dir(remote_dir)
        try:
            self._run_sftp_batch(f"cd {self._remote_dir_abs(normalized)}\n")
            return
        except SourceForgeError:
            pass

        commands = [f"cd {self.config.resolved_remote_root}"]
        if normalized:
            current = []
            for segment in normalized.split("/"):
                current.append(segment)
                commands.append(f"-mkdir {'/'.join(current)}")
        self._run_sftp_batch("\n".join(commands) + "\n")

    def list_remote(self, remote_dir: str) -> list[str]:
        normalized = normalize_remote_dir(remote_dir)
        commands = [f"cd {self._remote_dir_abs(normalized)}", "ls -l"]
        result = self._run_subprocess(
            [*_sftp_command(self.config), "-b", "-", f"{self.config.username}@{self.config.host}"],
            input_text="\n".join(commands) + "\n",
            capture_output=True,
        )
        return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]

    def list_remote_entries(self, remote_dir: str) -> list[RemoteEntry]:
        entries: list[RemoteEntry] = []
        for line in self.list_remote(remote_dir):
            parts = line.split(maxsplit=8)
            if len(parts) < 9:
                continue
            permissions = parts[0]
            name = parts[8]
            entries.append(RemoteEntry(name=name, is_dir=permissions.startswith("d"), raw=line))
        return entries

    def remote_file_exists(self, remote_dir: str, filename: str) -> bool:
        normalized_dir = normalize_remote_dir(remote_dir)
        validate_filename(filename)
        return any(line.endswith(f" {filename}") or line.endswith(f"/{filename}") for line in self.list_remote(normalized_dir))

    def rename_remote(self, old_path: str, new_path: str) -> None:
        old_abs = self._remote_path_abs(old_path)
        new_abs = self._remote_path_abs(new_path)
        self._run_sftp_batch(f"rename {old_abs} {new_abs}\n")

    def delete_remote(self, remote_path: str, confirm: bool = False) -> None:
        if not confirm:
            raise SourceForgeError("delete_remote requires confirm=True.")
        remote_abs = self._remote_path_abs(remote_path)
        self._run_sftp_batch(f"rm {remote_abs}\n")

    def remove_remote_dir(self, remote_path: str, confirm: bool = False) -> None:
        if not confirm:
            raise SourceForgeError("remove_remote_dir requires confirm=True.")
        remote_abs = self._remote_path_abs(remote_path)
        self._run_sftp_batch(f"rmdir {remote_abs}\n")

    def _rsync_destination(self, remote_path: str) -> str:
        remote_abs = self._remote_path_abs(remote_path)
        return f"{self.config.username}@{self.config.host}:{remote_abs}"

    def _run_rsync(self, local_file: Path, remote_path: str) -> None:
        command = [
            "rsync",
            "-avP",
            "--partial",
            "--progress",
            "--human-readable",
            "-e",
            shlex.join(_ssh_command(self.config)),
            str(local_file),
            self._rsync_destination(remote_path),
        ]
        try:
            self._run_command(command)
        except subprocess.CalledProcessError as error:
            raise SourceForgeError(f"rsync failed: {_subprocess_error_detail(error)}") from error

    def upload_file(self, local_file: str | Path, remote_dir: str, overwrite: bool = False) -> UploadResult:
        local_path = Path(local_file)
        if not local_path.exists():
            raise SourceForgeError(f"Local file not found: {local_path}")
        if not local_path.is_file():
            raise SourceForgeError(f"Local file is not a regular file: {local_path}")

        size_bytes = local_path.stat().st_size
        sha256 = hash_file(local_path)
        filename = validate_filename(local_path.name)
        normalized_dir = normalize_remote_dir(remote_dir)
        final_remote_path = f"{normalized_dir}/{filename}" if normalized_dir else filename
        try:
            self._run_rsync(local_path, final_remote_path)
        except SourceForgeError as error:
            if not _is_missing_remote_dir_error(str(error)):
                raise
            self.ensure_remote_dir(normalized_dir)
            self._run_rsync(local_path, final_remote_path)

        return UploadResult(
            service="SourceForge",
            success=True,
            url=generate_download_url(self.config.project, final_remote_path),
            payload={
                "remote_dir": normalized_dir,
                "remote_path": final_remote_path,
                "local_file": str(local_path),
                "size_bytes": size_bytes,
                "sha256": sha256,
            },
        )
