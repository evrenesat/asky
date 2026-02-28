# External Process Plugin Patterns

Plugins that wrap CLI tools (ffmpeg, yt-dlp, ImageMagick, etc.) follow the same
pattern: register one or more LLM tools via `TOOL_REGISTRY_BUILD`, run a subprocess
in the executor, store output in `context.data_dir`, and return a text summary the
LLM can relay to the user.

## How Files Arrive via XMPP

When an XMPP peer sends a file attachment, the XMPP client delivers it as an OOB URL
in the message payload. `XMPPService` classifies URLs by extension:

- Audio extensions (`.m4a`, `.mp3`, `.mp4`, `.wav`, etc.) → `VoiceTranscriber`
- Image extensions (`.jpg`, `.jpeg`, `.png`, `.webp`, `.gif`) → `ImageTranscriber`
- `.toml` files → session config upload
- All other URLs (including YouTube links, video files with unusual extensions) → **land in the text body** and are passed to the LLM as part of the query text

So for an LLM tool plugin: the user sends a YouTube URL or a `.mkv` file URL, the LLM
sees it in the query text, and calls the registered tool with the URL. The tool downloads
or processes the file and returns the result.

> **Limitation**: The core XMPP stack sends text responses only (`send_message`,
> `send_chat_message`). To share a processed file back, return a local file path or a
> web URL (e.g. served by the `gui_server` plugin) in the tool result text.
> XEP-0363 (HTTP Upload) is not currently wired in.

---

## Example: yt-dlp Plugin

Downloads YouTube (and other supported) URLs on demand.

### Directory layout

```
src/asky/plugins/yt_dlp_plugin/
├── __init__.py
├── plugin.py
└── downloader.py
```

### plugin.py

```python
from __future__ import annotations
import logging
from typing import Optional
from asky.plugins.base import AskyPlugin, PluginContext
from asky.plugins.hook_types import TOOL_REGISTRY_BUILD, ToolRegistryBuildContext

logger = logging.getLogger(__name__)

DOWNLOAD_TOOL_SCHEMA = {
    "name": "download_video",
    "description": (
        "Download a video or audio from a URL (YouTube, Vimeo, etc.) using yt-dlp. "
        "Use when the user shares a video URL and asks to download it. "
        "Returns the local file path."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The video URL to download.",
            },
            "audio_only": {
                "type": "boolean",
                "description": "Extract audio only (mp3). Default false.",
            },
        },
        "required": ["url"],
    },
}


class YtDlpPlugin(AskyPlugin):
    def __init__(self) -> None:
        self._ctx: Optional[PluginContext] = None

    def activate(self, context: PluginContext) -> None:
        self._ctx = context
        context.hook_registry.register(
            TOOL_REGISTRY_BUILD,
            self._on_tool_registry_build,
            plugin_name=context.plugin_name,
        )

    def deactivate(self) -> None:
        self._ctx = None

    def _on_tool_registry_build(self, payload: ToolRegistryBuildContext) -> None:
        if "download_video" in payload.disabled_tools:
            return
        payload.registry.register(
            "download_video",
            DOWNLOAD_TOOL_SCHEMA,
            self._execute_download,
        )

    def _execute_download(self, arguments: dict) -> dict:
        from asky.plugins.yt_dlp_plugin.downloader import download_video
        url = str(arguments.get("url", "")).strip()
        if not url:
            return {"error": "url is required", "file_path": None}
        audio_only = bool(arguments.get("audio_only", False))
        output_dir = self._ctx.data_dir / "downloads"
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            file_path = download_video(url, output_dir, audio_only=audio_only)
            return {"error": None, "file_path": str(file_path)}
        except Exception as exc:
            logger.warning("yt-dlp download failed url=%s: %s", url, exc)
            return {"error": str(exc), "file_path": None}
```

### downloader.py

```python
from __future__ import annotations
import subprocess
from pathlib import Path


def download_video(url: str, output_dir: Path, *, audio_only: bool = False) -> Path:
    """Download via yt-dlp. Returns path to downloaded file. Raises on failure."""
    output_template = str(output_dir / "%(title)s.%(ext)s")
    cmd = ["yt-dlp", "--no-playlist", "-o", output_template]
    if audio_only:
        cmd += ["-x", "--audio-format", "mp3"]
    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "yt-dlp failed")
    # yt-dlp prints the final filename with --print after-move; parse stdout instead
    for line in reversed(result.stdout.splitlines()):
        candidate = line.strip()
        if candidate and Path(candidate).exists():
            return Path(candidate)
    # fallback: return most recently modified file in output_dir
    files = sorted(output_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    if files:
        return files[0]
    raise RuntimeError("yt-dlp finished but output file not found")
```

### plugins.toml entry

```toml
[plugin.yt_dlp_plugin]
enabled = true
module  = "asky.plugins.yt_dlp_plugin.plugin"
class   = "YtDlpPlugin"
```

---

## Example: ffmpeg Plugin

Transcodes or processes a file URL sent via XMPP.

### plugin.py (key parts)

```python
FFMPEG_TOOL_SCHEMA = {
    "name": "process_video",
    "description": (
        "Download a video/audio file from a URL and re-encode it with ffmpeg. "
        "Use when the user shares a media file URL and requests conversion or processing. "
        "Returns the local output file path."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "input_url": {"type": "string", "description": "URL of the source file."},
            "output_format": {
                "type": "string",
                "description": "Output container format, e.g. 'mp4', 'mp3', 'gif'.",
            },
            "ffmpeg_args": {
                "type": "string",
                "description": "Extra ffmpeg arguments as a single string, e.g. '-vf scale=640:-1'.",
            },
        },
        "required": ["input_url", "output_format"],
    },
}
```

### executor logic

```python
import subprocess, urllib.request, hashlib
from pathlib import Path

def _execute_process(self, arguments: dict) -> dict:
    url = str(arguments.get("input_url", "")).strip()
    fmt = str(arguments.get("output_format", "mp4")).strip().lstrip(".")
    extra = str(arguments.get("ffmpeg_args", "")).strip()
    if not url:
        return {"error": "input_url is required", "file_path": None}

    work_dir = self._ctx.data_dir / "ffmpeg"
    work_dir.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha1(url.encode()).hexdigest()[:12]
    suffix = url.rsplit(".", 1)[-1].lower() if "." in url else "bin"
    input_path = work_dir / f"input_{digest}.{suffix}"
    output_path = work_dir / f"output_{digest}.{fmt}"

    try:
        urllib.request.urlretrieve(url, input_path)
        cmd = ["ffmpeg", "-y", "-i", str(input_path)]
        if extra:
            cmd += extra.split()
        cmd.append(str(output_path))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            return {"error": result.stderr[-500:], "file_path": None}
        return {"error": None, "file_path": str(output_path)}
    except Exception as exc:
        return {"error": str(exc), "file_path": None}
    finally:
        if input_path.exists():
            input_path.unlink(missing_ok=True)
```

---

## Subprocess Safety Rules

1. Never pass user-supplied strings directly as shell arguments. Always use `subprocess.run([...])` with a list, never `shell=True`.
2. Always set `timeout=` to prevent runaway processes.
3. Check `returncode` and surface `stderr` in the error return.
4. Store output in `context.data_dir` — this is plugin-scoped and gitignored.
5. Log warnings via `context.logger`, not `print`.

---

## Returning File Results to XMPP Users

Since the XMPP stack only supports text messages, tell the user the local path:

```python
return {
    "error": None,
    "file_path": "/Users/evren/.config/asky/plugins/yt_dlp_plugin/downloads/My Video.mp4",
    "message": "Downloaded successfully. File saved locally at the path above.",
}
```

If `gui_server` plugin is running, you can alternatively serve the file via its HTTP
port and return a `http://127.0.0.1:8766/...` URL the peer can fetch.
