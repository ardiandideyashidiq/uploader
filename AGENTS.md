# AGENTS.md

- Python 3.11 package; CLI entrypoints are `uploader.cli:main` (aliased as `uploader` and `up`) and `uploader.sourceforge_cli:main` (aliased as `up-sf`).
- Use `uv` for local work: `uv sync`, `uv run uploader <file> [--no-telegram]`, `uv run up <file>` (alias), `uv run python -m unittest discover -s tests`, or `uv run python -m unittest tests.test_uploaders.UploadGoFileTests.test_upload_gofile_creates_public_folder_and_returns_folder_url`.
- There is no repo-local pytest/ruff/mypy config; do not assume extra tooling or workflows.
- `AppConfig.from_sources` resolves values in this order: CLI flags, YAML config (`~/.config/uploader/config` or custom path via `--config`/`UPLOADER_CONFIG`), real environment variables, `.env` in the current working directory.
- `.env.example` is the template; lowercase aliases like `pixeldrain` and `telegram_chat_id` still work for backward compatibility.
- The CLI uploads to Pixeldrain, GoFile, and Vikingfile in parallel; `--single` is interactive and requires a TTY.
- New CLI flags: `--setup` (interactive YAML config creation), `--direct` (sendit.sh/temp.sh fallback upload), `--config` (custom config path).
- Telegram notifications use legacy Markdown formatting and include file metadata (SHA256 hash first 16 chars, size, upload date) with download links.
- Telegram config is required unless `--no-telegram` is set.
- `upload_gofile` is a two-step flow: account lookup, create a public folder, then upload the file and return the folder URL.
- `upload_direct` tries sendit.sh first, falls back to temp.sh if it fails.
- All upload functions calculate SHA256 hash and file size, included in UploadResult and Telegram notifications.
- `retry_upload` makes up to 3 attempts with 1s then 2s backoff for `requests.RequestException` and `RuntimeError`.
- Tests are stdlib `unittest` and mock `requests`; keep new unit tests network-free.
- Keep `.env` out of git.
- SourceForge FRS support is preserved with `up-sf` CLI entrypoint.
