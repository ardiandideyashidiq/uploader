# SourceForge FRS Upload, File Management, and Download Link Specification

Version: 1.0  
Scope: upload large release artifacts to SourceForge File Release System (FRS), manage remote files/folders, and return public download links.  
Non-goals: OTA updater JSON, Android build logic, ROM validation, website hosting, project-web hosting.

---

## 1. Background

SourceForge FRS exposes project release files through:

- Web File Manager
- SFTP
- SCP
- rsync over SSH

For large ROM files, the tool MUST use `rsync` for uploads by default because it can resume interrupted transfers. SFTP SHOULD be used for directory and file management operations such as `mkdir`, `ls`, `rename`, and `rm`.

Official FRS host:

```text
frs.sourceforge.net
```

Official FRS root path:

```text
/home/frs/project/{project_unix_name}/
```

Example:

```text
/home/frs/project/infinity-x/P661N/16/vanilla/
```

Public file URL pattern:

```text
https://sourceforge.net/projects/{project_unix_name}/files/{remote_relative_path}/{filename}/download
```

Example:

```text
https://sourceforge.net/projects/infinity-x/files/P661N/16/vanilla/Project_Infinity-X-3.10-P661N-05.05.2026-VANILLA-UNOFFICIAL.zip/download
```

---

## 2. Permissions and Authentication

### 2.1 Required SourceForge permission

The authenticated SourceForge account MUST be either:

- project admin, or
- granted the `release technician` permission for the project.

### 2.2 Supported authentication modes

The Python tool SHOULD support these modes:

```text
ssh_key
interactive_password
password_helper
```

#### `ssh_key`

Recommended for automation.

Expected behavior:

- Use normal OpenSSH identity discovery, or
- Accept an explicit private key path.

Example rsync SSH argument:

```bash
-e "ssh -i /path/to/private_key"
```

#### `interactive_password`

Acceptable for local terminal use.

Expected behavior:

- Spawn `rsync` or `sftp` with inherited stdin/stdout/stderr.
- Let OpenSSH prompt the user for the SourceForge password.
- Do not capture or log the password.

#### `password_helper`

Optional.

Expected behavior:

- Implement only if the caller explicitly enables it.
- Use a safe mechanism such as `pexpect`, OS keyring, or an external password provider.
- Never print the password.
- Never store the password in plaintext config.
- Avoid requiring `sshpass` unless the user explicitly accepts the security tradeoff.

---

## 3. Configuration Model

Minimum configuration:

```yaml
sourceforge:
  username: "your_sf_username"
  project: "infinity-x"
  host: "frs.sourceforge.net"
  remote_root: "/home/frs/project/infinity-x"
  auth_mode: "ssh_key"
  ssh_key_path: "~/.ssh/id_ed25519"
```

Runtime upload request:

```yaml
upload:
  local_file: "/builds/P661N/Project_Infinity-X-3.10-P661N-05.05.2026-VANILLA-UNOFFICIAL.zip"
  remote_dir: "P661N/16/vanilla"
  overwrite: false
  generate_checksums: true
  upload_sidecars: true
```

`remote_dir` MUST be relative to:

```text
/home/frs/project/{project_unix_name}/
```

The tool MUST reject absolute `remote_dir` values from user input unless explicitly operating in admin/debug mode.

---

## 4. Directory and File Naming Rules

### 4.1 Valid characters

Allowed characters for files and directories:

```text
- _ + . , = # ~ @ ! ( ) [ ] a-z A-Z 0-9 space
```

Disallowed characters include:

```text
& : % ? / * $ | { ; ^ } < > " ' unicode
```

Additional rules:

- Filename MUST NOT start with a space.
- Filename MUST NOT start with `.`
- Filename MUST NOT end with a space.
- Path separators `/` are only allowed between path segments, not inside a segment.

### 4.2 Recommended ROM layout

```text
{device}/{android_version}/{variant}/{filename}
```

Example:

```text
P661N/16/vanilla/Project_Infinity-X-3.10-P661N-05.05.2026-VANILLA-UNOFFICIAL.zip
X670/16/gapps/Project_Infinity-X-3.10-X670-05.05.2026-GAPPS-UNOFFICIAL.zip
```

### 4.3 Path normalization

The tool MUST normalize remote paths before executing commands.

Rules:

- Strip leading `/`.
- Collapse repeated `/`.
- Reject `..`.
- Reject empty path segments.
- Validate every segment using the SourceForge character rules.
- Construct absolute remote path internally only after validation.

Example:

```python
remote_abs = f"/home/frs/project/{project}/{remote_dir}/{filename}"
```

---

## 5. Core Operations

## 5.1 `ensure_remote_dir(remote_dir)`

Purpose:

Create remote folder hierarchy on SourceForge FRS.

Recommended implementation:

Use SFTP batch mode and issue `mkdir` for each cumulative path.

Example target:

```text
P661N/16/vanilla
```

Generated SFTP commands:

```text
cd /home/frs/project/infinity-x
-mkdir P661N
-mkdir P661N/16
-mkdir P661N/16/vanilla
```

The `-mkdir` prefix tells OpenSSH `sftp` batch mode to continue if the directory already exists.

Command shape:

```bash
sftp -b - your_sf_username@frs.sourceforge.net
```

Python subprocess shape:

```python
subprocess.run(
    ["sftp", "-b", "-", f"{username}@frs.sourceforge.net"],
    input=batch_commands,
    text=True,
    check=True,
)
```

For SSH key auth:

```python
subprocess.run(
    [
        "sftp",
        "-i", ssh_key_path,
        "-b", "-",
        f"{username}@frs.sourceforge.net",
    ],
    input=batch_commands,
    text=True,
    check=True,
)
```

Note: Some OpenSSH versions prefer SSH options via `-o` or `-S`. Test the actual environment. The tool MAY also use `sftp -oIdentityFile=/path/key`.

---

## 5.2 `upload_file(local_file, remote_dir, overwrite=False)`

Purpose:

Upload one large artifact to SourceForge FRS.

Default protocol:

```text
rsync over SSH
```

Required behavior:

1. Validate local file exists.
2. Validate local file is a regular file.
3. Validate filename and remote directory.
4. Ensure remote directory exists.
5. If `overwrite=false`, check whether remote file already exists.
6. Upload using `rsync -avP`.
7. Return structured upload result with local metadata and public URL.

Command shape:

```bash
rsync -avP -e ssh \
  "/local/path/ROM.zip" \
  "your_sf_username@frs.sourceforge.net:/home/frs/project/infinity-x/P661N/16/vanilla/"
```

For SSH key auth:

```bash
rsync -avP -e "ssh -i /path/to/private_key" \
  "/local/path/ROM.zip" \
  "your_sf_username@frs.sourceforge.net:/home/frs/project/infinity-x/P661N/16/vanilla/"
```

Recommended extra options:

```bash
--partial
--progress
--human-readable
```

Equivalent:

```bash
rsync -avP --human-readable -e ssh ...
```

Do not use `--delete` for single-file uploads.

### 5.2.1 Overwrite handling

If `overwrite=false`, the tool MUST check the remote path before uploading.

Implementation options:

- `sftp ls remote_file`
- `sftp ls remote_dir` and match filename
- optimistic upload to a temporary name, then rename after validation

Recommended safe upload mode:

```text
filename.zip.uploading
```

Flow:

1. Upload local file as `filename.zip.uploading`.
2. Verify remote temporary file appears in listing.
3. Rename remote temp file to final filename.
4. Return final download link.

This prevents users from downloading a partially uploaded final filename.

Example:

```bash
rsync -avP ROM.zip \
  user@frs.sourceforge.net:/home/frs/project/project/device/16/vanilla/ROM.zip.uploading
```

Then SFTP:

```text
rename /home/frs/project/project/device/16/vanilla/ROM.zip.uploading /home/frs/project/project/device/16/vanilla/ROM.zip
```

Caveat:

- If resuming uploads is important, keep the `.uploading` temp file and resume into the same temp filename.
- If upload completes but rename fails, retry rename before re-uploading.

---

## 5.3 `upload_many(files, remote_dir, overwrite=False)`

Purpose:

Upload ROM plus sidecar files such as `.md5`, `.sha256`, `.json`, `.txt`.

Behavior:

- Ensure remote directory once.
- Upload files with one rsync call when possible.
- Return one result per file.

Command shape:

```bash
rsync -avP -e ssh \
  ROM.zip ROM.zip.md5 ROM.zip.sha256 \
  user@frs.sourceforge.net:/home/frs/project/project/P661N/16/vanilla/
```

Recommended order:

1. Checksums and metadata files
2. ROM zip temp file
3. Rename ROM zip temp file to final filename
4. Optional: upload/update manifest after ROM is complete

For this spec, OTA manifest behavior is out of scope.

---

## 5.4 `list_remote(remote_dir)`

Purpose:

List files/folders under a remote FRS directory.

Use SFTP:

```text
cd /home/frs/project/infinity-x/P661N/16/vanilla
ls -l
```

Command shape:

```bash
sftp -b - user@frs.sourceforge.net
```

Batch:

```text
cd /home/frs/project/infinity-x/P661N/16/vanilla
ls -l
```

Output parsing:

- SHOULD parse filename.
- MAY parse size, permissions, and modified time.
- MUST tolerate spaces in filenames.
- SHOULD provide raw output for debugging.

Recommended Python return:

```json
{
  "remote_dir": "P661N/16/vanilla",
  "items": [
    {
      "name": "ROM.zip",
      "type": "file",
      "size": 3221225472,
      "raw": "-rw-r--r-- ..."
    }
  ]
}
```

---

## 5.5 `delete_remote(remote_path)`

Purpose:

Delete a remote file.

Use SFTP:

```text
rm /home/frs/project/infinity-x/P661N/16/vanilla/ROM.zip
```

Rules:

- Deleting folders is not required for MVP.
- Require explicit confirmation flag in CLI or API.
- Never support wildcard deletion by default.
- Reject `*`, `?`, and unvalidated paths.

Recommended Python API:

```python
delete_remote(remote_path: str, confirm: bool = False)
```

If `confirm` is false, raise an error.

---

## 5.6 `rename_remote(old_path, new_path)`

Purpose:

Rename or move files/folders inside the same SourceForge project FRS tree.

Use SFTP:

```text
rename /home/frs/project/infinity-x/old/path.zip /home/frs/project/infinity-x/new/path.zip
```

Rules:

- Both paths MUST be under the same project root.
- Validate old and new path segments.
- If renaming a public file, warn that SourceForge download statistics are filename-based and may reset after rename.

---

## 5.7 `generate_download_url(remote_path)`

Purpose:

Generate the public SourceForge download URL for a remote FRS file.

Input:

```text
P661N/16/vanilla/ROM.zip
```

Output:

```text
https://sourceforge.net/projects/infinity-x/files/P661N/16/vanilla/ROM.zip/download
```

Rules:

- Use the project UNIX name in the URL.
- Use the path relative to `/home/frs/project/{project}/`.
- URL-encode each path segment.
- Append `/download`.

Python implementation:

```python
from urllib.parse import quote

def generate_download_url(project: str, remote_path: str) -> str:
    segments = [s for s in remote_path.strip("/").split("/") if s]
    encoded = "/".join(quote(s, safe="") for s in segments)
    return f"https://sourceforge.net/projects/{quote(project, safe='')}/files/{encoded}/download"
```

Examples:

```python
generate_download_url(
    "infinity-x",
    "P661N/16/vanilla/Project_Infinity-X-3.10-P661N-05.05.2026-VANILLA-UNOFFICIAL.zip",
)
```

Returns:

```text
https://sourceforge.net/projects/infinity-x/files/P661N/16/vanilla/Project_Infinity-X-3.10-P661N-05.05.2026-VANILLA-UNOFFICIAL.zip/download
```

---

## 5.8 `verify_download_url(url)`

Purpose:

Check whether the generated public download link resolves.

Recommended command:

```bash
curl -L --fail --range 0-0 -o /dev/null -sS "$url"
```

Why:

- SourceForge download URLs redirect to mirrors.
- `-L` follows redirects.
- `--range 0-0` downloads only the first byte when supported.
- `--fail` exits non-zero on HTTP errors.

Python behavior:

```python
result = subprocess.run(
    ["curl", "-L", "--fail", "--range", "0-0", "-o", "/dev/null", "-sS", url],
    check=False,
)
available = result.returncode == 0
```

Verification SHOULD be optional because mirrors may need time to reflect newly uploaded files.

---

## 6. Checksum Sidecar Files

Optional but recommended.

Generated files:

```text
ROM.zip.md5
ROM.zip.sha256
```

Python implementation:

```python
import hashlib
from pathlib import Path

def hash_file(path: Path, algorithm: str = "sha256", chunk_size: int = 8 * 1024 * 1024) -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()
```

Sidecar file format:

```text
{hex_digest}  {filename}
```

Example:

```text
04f69e6ad15b6a7026bdca666359059f  Project_Infinity-X-3.10-P661N-05.05.2026-VANILLA-UNOFFICIAL.zip
```

---

## 7. Python Module Design

Recommended module name:

```text
sourceforge_frs.py
```

### 7.1 Data classes

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

AuthMode = Literal["ssh_key", "interactive_password", "password_helper"]

@dataclass
class SourceForgeConfig:
    username: str
    project: str
    host: str = "frs.sourceforge.net"
    remote_root: Optional[str] = None
    auth_mode: AuthMode = "ssh_key"
    ssh_key_path: Optional[Path] = None

    def resolved_remote_root(self) -> str:
        return self.remote_root or f"/home/frs/project/{self.project}"
```

```python
@dataclass
class UploadResult:
    local_file: str
    filename: str
    remote_dir: str
    remote_path: str
    remote_abs_path: str
    size: int
    md5: Optional[str]
    sha256: Optional[str]
    download_url: str
    uploaded: bool
    verified: Optional[bool]
```

### 7.2 Main client

```python
class SourceForgeFRSClient:
    def __init__(self, config: SourceForgeConfig):
        self.config = config

    def ensure_remote_dir(self, remote_dir: str) -> None:
        ...

    def upload_file(
        self,
        local_file: str | Path,
        remote_dir: str,
        overwrite: bool = False,
        use_temp_name: bool = True,
        verify: bool = False,
    ) -> UploadResult:
        ...

    def upload_many(
        self,
        local_files: list[str | Path],
        remote_dir: str,
        overwrite: bool = False,
    ) -> list[UploadResult]:
        ...

    def list_remote(self, remote_dir: str) -> dict:
        ...

    def delete_remote(self, remote_path: str, confirm: bool = False) -> None:
        ...

    def rename_remote(self, old_path: str, new_path: str) -> None:
        ...

    def generate_download_url(self, remote_path: str) -> str:
        ...

    def verify_download_url(self, url: str) -> bool:
        ...
```

---

## 8. CLI Design

Recommended command name:

```text
sf-frs
```

### 8.1 Upload one file

```bash
sf-frs upload \
  --project infinity-x \
  --user your_sf_username \
  --remote-dir P661N/16/vanilla \
  --file Project_Infinity-X-3.10-P661N-05.05.2026-VANILLA-UNOFFICIAL.zip
```

Expected output:

```json
{
  "filename": "Project_Infinity-X-3.10-P661N-05.05.2026-VANILLA-UNOFFICIAL.zip",
  "remote_path": "P661N/16/vanilla/Project_Infinity-X-3.10-P661N-05.05.2026-VANILLA-UNOFFICIAL.zip",
  "size": 1662769662,
  "download_url": "https://sourceforge.net/projects/infinity-x/files/P661N/16/vanilla/Project_Infinity-X-3.10-P661N-05.05.2026-VANILLA-UNOFFICIAL.zip/download",
  "uploaded": true,
  "verified": null
}
```

### 8.2 Upload with checksums

```bash
sf-frs upload \
  --project infinity-x \
  --user your_sf_username \
  --remote-dir P661N/16/vanilla \
  --file ROM.zip \
  --checksum md5 \
  --checksum sha256
```

### 8.3 List remote directory

```bash
sf-frs list \
  --project infinity-x \
  --user your_sf_username \
  --remote-dir P661N/16/vanilla
```

### 8.4 Delete remote file

```bash
sf-frs delete \
  --project infinity-x \
  --user your_sf_username \
  --remote-path P661N/16/vanilla/ROM.zip \
  --confirm
```

### 8.5 Rename remote file

```bash
sf-frs rename \
  --project infinity-x \
  --user your_sf_username \
  --old-path P661N/16/vanilla/ROM.zip.uploading \
  --new-path P661N/16/vanilla/ROM.zip
```

### 8.6 Generate download URL only

```bash
sf-frs link \
  --project infinity-x \
  --remote-path P661N/16/vanilla/ROM.zip
```

Output:

```text
https://sourceforge.net/projects/infinity-x/files/P661N/16/vanilla/ROM.zip/download
```

---

## 9. Error Handling

The tool MUST classify common failures.

### 9.1 Local validation errors

Examples:

```text
LOCAL_FILE_NOT_FOUND
LOCAL_FILE_NOT_REGULAR
INVALID_FILENAME
INVALID_REMOTE_DIR
INVALID_PROJECT_NAME
```

### 9.2 Remote command errors

Examples:

```text
AUTH_FAILED
PERMISSION_DENIED
REMOTE_DIR_NOT_FOUND
REMOTE_FILE_EXISTS
REMOTE_FILE_NOT_FOUND
RSYNC_FAILED
SFTP_FAILED
```

### 9.3 Network errors

Examples:

```text
NETWORK_TIMEOUT
CONNECTION_RESET
DNS_FAILED
MIRROR_VERIFY_FAILED
```

### 9.4 Retry policy

Recommended:

- Retry `rsync` upload up to 2 times for transient network failures.
- Do not retry auth failures.
- Do not retry invalid path errors.
- For verification failure, return `verified=false` but do not mark upload as failed if `rsync` succeeded.

---

## 10. Logging Rules

Log:

- operation name
- local path
- remote path
- file size
- command exit code
- generated download URL
- verification result

Do not log:

- passwords
- private key contents
- full environment variables
- command output that may contain secrets

Recommended log levels:

```text
INFO: operation start/end, file size, generated link
WARNING: verification failed, overwrite skipped, retrying
ERROR: subprocess failed, validation failed
DEBUG: raw sftp listing, rsync stderr when safe
```

---

## 11. Security Rules

The tool MUST:

- Use argument lists for subprocess calls, not shell strings.
- Avoid `shell=True`.
- Validate remote paths before use.
- Reject `..`.
- Reject wildcards for delete.
- Never print credentials.
- Prefer SSH key auth for CI/automation.
- Keep passwords out of config files.

The tool SHOULD:

- Use `known_hosts` verification.
- Let users manually accept SourceForge SSH host fingerprint on first connection.
- Provide a `--strict-host-key-checking` option for CI.

---

## 12. Minimal MVP Implementation Plan

### Phase 1

Implement:

- config model
- path validation
- download URL generator
- `ensure_remote_dir`
- `upload_file` using rsync
- JSON result output

### Phase 2

Add:

- list remote
- delete remote
- rename remote
- checksum sidecar generation
- upload multiple files

### Phase 3

Add:

- safe temp upload + rename
- verification with curl
- retry policy
- structured error codes
- tests

---

## 13. Test Cases

### 13.1 URL generation

Input:

```text
project = infinity-x
remote_path = P661N/16/vanilla/ROM.zip
```

Expected:

```text
https://sourceforge.net/projects/infinity-x/files/P661N/16/vanilla/ROM.zip/download
```

### 13.2 URL generation with spaces

Input:

```text
remote_path = P661N/16/vanilla/My ROM.zip
```

Expected:

```text
https://sourceforge.net/projects/infinity-x/files/P661N/16/vanilla/My%20ROM.zip/download
```

### 13.3 Invalid filename

Input:

```text
ROM:bad.zip
```

Expected error:

```text
INVALID_FILENAME
```

### 13.4 Path traversal

Input:

```text
../secret/ROM.zip
```

Expected error:

```text
INVALID_REMOTE_DIR
```

### 13.5 Upload existing file with overwrite disabled

Expected error:

```text
REMOTE_FILE_EXISTS
```

### 13.6 Delete without confirmation

Expected error:

```text
CONFIRMATION_REQUIRED
```

---

## 14. Official References

SourceForge Release Files for Download:

```text
https://sourceforge.net/p/forge/documentation/Release%20Files%20for%20Download/
```

SourceForge rsync:

```text
https://sourceforge.net/p/forge/documentation/rsync/
```

SourceForge SFTP:

```text
https://sourceforge.net/p/forge/documentation/SFTP/
```

SourceForge command-line download URLs:

```text
https://sourceforge.net/p/forge/documentation/Downloading%20files%20via%20the%20command%20line/
```

SourceForge Files documentation:

```text
https://sourceforge.net/p/forge/documentation/Files/
```
