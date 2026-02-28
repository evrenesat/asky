# Plan: XEP-0363 HTTP File Upload for XMPP Plugin

## Overview

Add XEP-0363 (HTTP File Upload) support to the `xmpp_daemon` plugin.
XEP-0363 lets XMPP clients upload files to an HTTP server provided by the XMPP
server, and share the resulting download URL with other participants.

**Protocol flow:**
1. Client discovers the upload service component via XEP-0030 (service discovery).
2. Client sends an IQ request with filename, file size, and content-type.
   The server responds with a PUT URL, a GET URL, and any required HTTP headers.
3. Client HTTP-PUTs the file to the PUT URL.
4. Client sends the GET URL to the recipient as an XMPP message with an OOB
   (XEP-0066 `jabber:x:oob`) stanza so supporting clients show an inline file.

Slixmpp ships a native `xep_0363` plugin that handles steps 2–4 via a single
`upload_file()` coroutine. Our XMPP client is asyncio-based but called from a
regular Python thread; uploads must therefore be bridged via
`asyncio.run_coroutine_threadsafe()`.

**Goal:** expose a simple, synchronous-from-caller-perspective
`FileUploadService` singleton that other plugins can import from
`asky.plugins.xmpp_daemon.file_upload` to upload a local file and deliver it
to an XMPP JID in one call.

---

## Phases

### Phase 1: Register xep_0363 and add upload primitives to `AskyXMPPClient`

**Files modified:** `src/asky/plugins/xmpp_daemon/xmpp_client.py`

**Tasks:**

1. Add `"xep_0363"` to the plugin registration loop in `AskyXMPPClient.__init__()`.
   It must come after `"xep_0030"` (service discovery is a dependency).
   Before: the loop registers `xep_0045`, `xep_0050`, `xep_0004`, `xep_0030`, `xep_0071`, `xep_0308`.
   After: add `"xep_0363"` to that tuple.

2. Add method `upload_file(self, file_path: str, *, content_type: str = "") -> str`
   to `AskyXMPPClient`:
   - Opens the file in binary mode.
   - Gets the `xep_0363` plugin via `self.get_plugin("xep_0363")`.
   - Raises `DaemonUserError("XMPP upload service not available.")` if plugin is None.
   - Calls the plugin's `upload_file()` coroutine (async) via
     `asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=60)`.
   - Returns the download URL string.
   - Lets `UploadServiceNotFound`, `FileTooBig`, and `HTTPError` propagate to caller.

3. Add method `send_oob_message(self, *, to_jid: str, url: str, body: str, message_type: str) -> None`
   to `AskyXMPPClient`:
   - Constructs a message stanza (via `make_message`) with the given body.
   - Appends an OOB `<x xmlns="jabber:x:oob"><url>…</url></x>` child element.
   - Dispatches via `_dispatch_client_send_stanza` (re-using the existing pattern).
   - This stanza format causes supporting clients (Conversations, Gajim, etc.)
     to display an inline download link or file preview.

**Constraints:**
- Do NOT introduce a new asyncio loop. Reuse `self.loop`.
- If `self.loop` is None (client not connected), raise `DaemonUserError`.
- Do not change existing send or connect methods.

**Verification:**
```
uv run pytest tests/test_xmpp_client.py -x -q
```

---

### Phase 2: Create `FileUploadService` with module-level singleton

**Files created:** `src/asky/plugins/xmpp_daemon/file_upload.py`
**Files modified:** `src/asky/plugins/xmpp_daemon/xmpp_service.py`

**Tasks:**

1. Create `file_upload.py` with:

   ```
   Constants:
     UPLOAD_TIMEOUT_SECONDS = 60
     UPLOAD_MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB hard guard

   Exceptions:
     FileUploadError(Exception)  — wraps all upload failures with a human message

   Class FileUploadService:
     __init__(self, client: AskyXMPPClient) -> None
       Stores the client reference.

     upload_and_send(
       self,
       *,
       file_path: str,
       to_jid: str,
       message_type: str,
       filename: str = "",          # override the on-disk name if desired
       content_type: str = "",      # auto-detected if empty
       caption: str = "",           # optional body text alongside the file URL
     ) -> str
       — Validates file exists and is within UPLOAD_MAX_FILE_SIZE_BYTES.
       — Determines filename from file_path if not provided.
       — Calls self._client.upload_file() to get the download URL.
       — Calls self._client.send_oob_message() to deliver the URL.
       — Returns the download URL.
       — Wraps DaemonUserError / slixmpp exceptions in FileUploadError with
         a clear human-readable message. Does NOT swallow exceptions silently.

   Module-level singleton:
     _service: Optional[FileUploadService] = None

     def set_file_upload_service(service: FileUploadService) -> None:
       Sets the singleton.

     def get_file_upload_service() -> Optional[FileUploadService]:
       Returns the singleton, or None if XMPP is not running.
   ```

2. In `XMPPService.__init__()` (in `xmpp_service.py`), after the `AskyXMPPClient`
   is constructed, instantiate `FileUploadService(client)` and call
   `set_file_upload_service(service)`. Also call `set_file_upload_service(None)`
   in `XMPPService.stop()` to clear the reference when XMPP disconnects.

**Constraints:**
- `file_upload.py` must import from `asky.plugins.xmpp_daemon.xmpp_client` only
  (no daemon core, no other plugin packages).
- `get_file_upload_service()` must return `None` gracefully when XMPP is stopped;
  callers are responsible for handling `None`.
- Do NOT auto-send a caption as a separate message. Keep OOB + body in one stanza.

**Verification:**
```
uv run pytest tests/test_xmpp_file_upload.py -x -q
uv run pytest tests/test_xmpp_daemon.py -x -q
```

---

### Phase 3: Unit tests

**Files created:** `tests/test_xmpp_file_upload.py`

**Tasks:**

Write tests covering:

1. `AskyXMPPClient.upload_file()`:
   - Happy path: mock `xep_0363` plugin's `upload_file` coroutine returns a URL;
     assert correct URL returned.
   - `xep_0363` plugin not available → `DaemonUserError` raised.
   - `self.loop` is None → `DaemonUserError` raised.
   - Slixmpp `UploadServiceNotFound` propagates as-is.

2. `AskyXMPPClient.send_oob_message()`:
   - Verifies the constructed stanza contains `<x xmlns="jabber:x:oob"><url>…</url></x>`.
   - Verifies message body is set correctly.

3. `FileUploadService.upload_and_send()`:
   - Happy path: mock client methods; assert download URL is returned, OOB message sent.
   - File not found → `FileUploadError`.
   - File exceeds `UPLOAD_MAX_FILE_SIZE_BYTES` → `FileUploadError`.
   - Client raises `DaemonUserError` → wrapped in `FileUploadError`.

4. Singleton:
   - `get_file_upload_service()` returns `None` before `set_file_upload_service()` called.
   - After `set_file_upload_service(service)`, returns the service.
   - After `set_file_upload_service(None)`, returns `None` again.

**Constraints:**
- All tests must mock slixmpp; no real network calls.
- Each test must finish in under 1 second.
- Do not import `rumps`, `slixmpp`, or any optional dep at module level in tests.

**Verification:**
```
uv run pytest tests/test_xmpp_file_upload.py -x -q -v
uv run pytest -x -q   # full suite, no regression
```

---

## Notes

- The slixmpp `xep_0363` plugin's `upload_file()` signature: `upload_file(filename, size, content_type, input=<BinaryIO>)`.
  The exact signature may vary by slixmpp version; wrap in try/except and
  fall back to keyword-argument form.
- Slixmpp versions prior to 1.8 may not ship `xep_0363`. The existing
  registration try/except block in `AskyXMPPClient` already handles that;
  `get_plugin("xep_0363")` returning `None` is the graceful failure path.
- OOB namespace to use for outbound: `jabber:x:oob` (already in `OOB_XML_NAMESPACES`).
- No config keys needed for Phase 1–3. If upload quotas or server-specific
  options are required later, add config keys then.
- XEP-0363 requires the XMPP server to have the upload component enabled
  (e.g., `mod_http_upload` in ejabberd/Prosody). If the server lacks this,
  `UploadServiceNotFound` is raised; surface this as a clear error message.

Sources:
- [XEP-0363: HTTP File Upload](https://xmpp.org/extensions/xep-0363.html)
- [slixmpp XEP-0363 API](https://slixmpp.readthedocs.io/en/latest/api/plugins/xep_0363.html)
