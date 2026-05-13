# uploader

```bash
uv tool install git+https://github.com/ardiandideyashidiq/uploader.git
```

## Setup

Run interactive setup to configure credentials:

```bash
uploader --setup
```

When prompted, paste your config in this format and press Esc+Enter:

```yaml
pixeldrain_key: YOUR_PIXELDRAIN_KEY
gofile_key: YOUR_GOFILE_KEY
vikingfile_user: YOUR_VIKINGFILE_USER
# Optional (leave empty or delete lines below):
telegram_bot_token:
telegram_chat_id:
```

Config saved to `~/.config/uploader/config` (YAML).

## Usage

Upload a file (parallel to Pixeldrain, GoFile, Vikingfile):

```bash
uploader <file>
# or use the short alias:
up <file>
```

Upload to a single service:

```bash
uploader -s <file>
```

Direct-link upload (sendit.sh with temp.sh fallback):

```bash
uploader --direct <file>
```

Skip Telegram notification:

```bash
uploader --no-telegram <file>
```

## Telegram Notifications

Telegram notifications include:
- Filename prominently at the top
- Service status (success/failure) in a blockquote
- Download buttons (InlineKeyboard) below the message for each successful upload
- Expandable file details accordion with:
  - File type (MIME)
  - File size (human-readable + bytes)
  - Full SHA256 hash
  - Upload date in WIB (UTC+7) timezone

Notifications use Telegram HTML parse mode with blockquotes, expandable blockquotes, and InlineKeyboard URL buttons.

Example:

```html
<b>Upload Complete</b>

<b>File:</b> <code>archive.zip</code>
<blockquote><b>Services</b>
• <b>Pixeldrain:</b> ok
• <b>GoFile:</b> ok
• <b>Vikingfile:</b> <tg-spoiler>failed</tg-spoiler>
  <i>Temporary upstream error</i></blockquote>

<blockquote expandable><b>File Details</b>
Type: <code>application/zip</code>
Size: <code>1.24 GB (1331439821 bytes)</code>
SHA256: <code>a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6</code>
Uploaded: <code>2026-05-13 22:12:03 WIB (UTC+7)</code></blockquote>

[Pixeldrain] [GoFile]   <- inline keyboard buttons below message
```

## Config

Edit config manually at `~/.config/uploader/config`:

```yaml
pixeldrain_key: your_pixeldrain_key
gofile_key: your_gofile_key
vikingfile_user: your_vikingfile_user
telegram_bot_token: your_bot_token  # optional
telegram_chat_id: your_chat_id      # optional
```

Custom config path:

```bash
uploader --config /path/to/config <file>
```

Force reconfigure:

```bash
uploader --setup
```

## Direct Downloader

Tries sendit.sh first, falls back to temp.sh if it fails.

- sendit.sh links work in browser, curl, wget
- temp.sh files expire after 3 days, max 4GB

## SourceForge FRS

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
Telegram is required for SourceForge uploads unless `--no-telegram` is used; upload notifications include an expandable details accordion with file size, SHA256, remote path, file type, upload date (WIB), and download link.

## Legacy .env Support

The project also supports `.env` files for backward compatibility. Create a `.env` file from `.env.example` and fill in your keys. Config precedence: CLI flags > YAML config > .env > environment variables.
