# uploader

```bash
uv tool install git+https://github.com/rdndds/uploader.git
```

Create a `.env` file from `.env.example` and fill in your keys.

By default the CLI uploads to Pixeldrain, GoFile, and Vikingfile in parallel.
Set `VIKINGFILE_USER` to upload into a Vikingfile account, or leave it empty for anonymous uploads.

SourceForge FRS mode is CLI-only and uploads with rsync:

```bash
uv run up-sf upload P661N/16/vanilla ROM.zip --username your_sf_username --project infinity-x
uv run up-sf upload P661N/16/vanilla ROM.zip --username your_sf_username --project infinity-x --no-telegram
uv run up-sf list P661N/16/vanilla --username your_sf_username --project infinity-x
uv run up-sf rename old.zip new.zip --username your_sf_username --project infinity-x
uv run up-sf delete old.zip --confirm --username your_sf_username --project infinity-x
uv run up-sf link P661N/16/vanilla/ROM.zip --project infinity-x
```

SourceForge config can be passed as flags, set in `.env`, or stored in `~/.config/uploader/sourceforge.json` (or `$XDG_CONFIG_HOME/uploader/sourceforge.json`).
SourceForge uploads try rsync first and only use SFTP to create the remote directory if rsync reports that it does not exist.
Existing remote files may be replaced by default.
Telegram is required for SourceForge uploads unless `--no-telegram` is used; upload notifications include the file size, SHA256, remote path, and download link.
