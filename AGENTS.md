# AGENTS.md

- Python 3.11 package; CLI entrypoint is `uploader.cli:main`.
- Use `uv` for local work. Typical commands: `uv sync`, `uv run uploader <file> [--no-telegram]`, `uv run python -m unittest discover -s tests`, `uv run python -m unittest tests.test_uploaders.UploadGoFileTests.test_upload_gofile_creates_public_folder_and_returns_folder_url`.
- There is no repo-local pytest/ruff/mypy config here; do not assume extra tooling or workflows.
- `AppConfig.from_sources` resolves values in this order: CLI flags, real environment variables, `.env` in the current working directory, then built-in defaults.
- `.env.example` is the template; lowercase aliases like `pixeldrain` and `telegram_chat_id` still work.
- The CLI uploads to Pixeldrain and GoFile in parallel with 2 threads and requires Telegram config unless `--no-telegram` is set.
- `upload_gofile` is a two-step flow: account lookup, create a public folder, then upload the file and return the folder URL.
- Tests are stdlib `unittest` and mock `requests`; keep new unit tests network-free.
- Keep `.env` out of git.
