# Playwright Browser Plugin — Implementation Plan

## Context

`fetch_url_document` (in `retrieval.py`) uses `requests` + `trafilatura` to fetch and extract page content. Aggressive bot-protection (Cloudflare, hCaptcha, fingerprinting) blocks this on many sites even for real users. This plugin adds Playwright as an optional drop-in backend, with persistent session support and a visible (non-headless) browser, and allows per-call-site configuration of when to use it.

## End State (observable behavior)

- `fetch_url_document` first checks a new `FETCH_URL_OVERRIDE` hook; if a plugin intercepts, that result is used.
- A new `playwright_browser` plugin provides that interception.
- Plugin uses sync Playwright (non-headless) with a saved session state on disk.
- Plugin is configurable per call-site (`get_url_content`, `get_url_details`, `shortlist`, `research`).
- `asky --playwright-login <url>` opens the browser to a URL so the user can log in; session is saved and reused.
- If a CAPTCHA/challenge is detected mid-fetch, the browser pops up for the user to solve it.
- On Playwright failure, transparently falls back to `requests`/trafilatura.
- Plugin is disabled by default in the bundled config; users opt in.

---

## Assumptions & Constraints

- Playwright sync API only; no asyncio introduced.
- Thread safety: a `threading.Lock` serializes all Playwright operations. Parallel shortlist fetches will queue through the lock. This is intentional — avoid rate-limiting by serializing Playwright calls.
- No headless mode (`headless=False` always; no config flag for this because it defeats the anti-fingerprinting goal).
- Session state stored globally (not per-domain) in `context.data_dir / "session.json"`.
- Playwright browser process stays alive for the duration of the asky process (lazy-started), closed in `deactivate()`. Between asky invocations, sessions persist via `session.json`. A background "always-on" daemon browser is out of scope for v1.
- Content extraction after Playwright fetch reuses trafilatura directly (not through `fetch_url_document`'s internal pipeline). Portal detection and HTML fallback are excluded from the Playwright path in v1.
- The `research/tools.py:_fetch_and_parse` call site currently passes no `trace_context`. We add `trace_context={"tool_name": "research"}` there so it can be intercepted.
- Plugin disabled by default in bundled `plugins.toml`; requires `uv pip install 'asky-cli[playwright]'` + `playwright install chromium`.

---

## Implementation Steps

### Step 1 — Add `FETCH_URL_OVERRIDE` hook to `hook_types.py`

**File:** `src/asky/plugins/hook_types.py`

Add constant:
```python
FETCH_URL_OVERRIDE = "FETCH_URL_OVERRIDE"
```

Add to `SUPPORTED_HOOK_NAMES`.

Add dataclass:
```python
@dataclass
class FetchURLContext:
    """Mutable payload for fetch-URL override hooks.

    Plugins that handle the request must set ``result`` to the same
    dict structure returned by ``fetch_url_document``.  Leaving it as
    ``None`` passes control to the next plugin (or to the default
    requests/trafilatura pipeline).
    """
    url: str
    output_format: str
    include_links: bool
    max_links: Optional[int]
    trace_callback: Optional[Any]
    trace_context: Optional[Dict[str, Any]]
    result: Optional[Dict[str, Any]] = None
```

### Step 2 — Invoke the hook in `retrieval.py`

**File:** `src/asky/retrieval.py`

At the top of `fetch_url_document`, after `requested_url` is validated and sanitized, add:

```python
_plugin_override = _try_fetch_url_plugin_override(
    url=requested_url,
    output_format=output_format,
    include_links=include_links,
    max_links=max_links,
    trace_callback=trace_callback,
    trace_context=trace_context,
)
if _plugin_override is not None:
    return _plugin_override
```

Add helper (uses lazy imports to avoid circular dependency):

```python
def _try_fetch_url_plugin_override(
    url: str,
    output_format: str,
    include_links: bool,
    max_links: Optional[int],
    trace_callback: Optional[TraceCallback],
    trace_context: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Ask plugins for an override result; returns None to use the default pipeline."""
    try:
        from asky.plugins.hook_types import FETCH_URL_OVERRIDE, FetchURLContext
        from asky.plugins.runtime import get_or_create_plugin_runtime
    except ImportError:
        return None
    runtime = get_or_create_plugin_runtime()
    if runtime is None:
        return None
    ctx = FetchURLContext(
        url=url,
        output_format=output_format,
        include_links=include_links,
        max_links=max_links,
        trace_callback=trace_callback,
        trace_context=trace_context,
    )
    runtime.hooks.invoke(FETCH_URL_OVERRIDE, ctx)
    return ctx.result
```

Placement: immediately after the empty-URL guard, before `started = time.perf_counter()` (move the timer to after this block).

### Step 3 — Add `trace_context` to `research/tools.py`

**File:** `src/asky/research/tools.py`

In `_fetch_and_parse`, update the `fetch_url_document` call to pass:
```python
trace_context={"tool_name": "research"},
```

This makes it interceptable when the user includes `"research"` in their `intercept` list.

### Step 4 — Expose link-extraction helper in `retrieval.py`

**File:** `src/asky/retrieval.py`

Extract the existing internal link-normalization logic into a package-internal function:

```python
def _extract_and_normalize_links(
    html: str, base_url: str, max_links: Optional[int]
) -> List[Dict[str, str]]:
    """Extract and normalize anchor links from HTML. Package-internal."""
    ...
```

This is refactoring internal code only; no public API change.

### Step 5 — Create plugin package

**Files to create:**

#### `src/asky/plugins/playwright_browser/__init__.py`
Empty.

#### `src/asky/plugins/playwright_browser/browser.py`

`PlaywrightBrowserManager` class using sync Playwright.

**Responsibilities:**
- Lazy-start the Playwright browser on first use (`_ensure_started()`).
- Load session state from `session_path` on first use; save after every successful fetch.
- Per-domain same-site delay: track `last_request_time: Dict[str, float]` (keyed by `urllib.parse.urlparse(url).netloc`); sleep a random duration in `[same_site_min_delay_ms, same_site_max_delay_ms]` before fetching if the domain was recently visited.
- `fetch_page(url) -> Tuple[str, str]` — returns `(html, final_url)`.
- CAPTCHA/challenge detection inside `fetch_page`:
  - Trigger conditions: `page.url` changed to a known challenge domain, HTTP status 403/429 after navigation, or DOM contains any selector from `CHALLENGE_SELECTORS`.
  - On detection: emit `sys.stderr` warning, wait for page content to change (poll loop up to `CHALLENGE_WAIT_TIMEOUT_MS`), then continue. Browser window is visible so user solves it naturally.
- `open_login_session(url: str)` — navigate to URL, print instructions to stderr, block until user presses Enter in terminal, save session.
- `close()` — saves session state, stops playwright cleanly.
- All public methods hold `self._lock` (threading.Lock).

Module-level constants:
```python
CHALLENGE_SELECTORS = [
    ".cf-challenge", "#challenge-form",
    "[data-recaptcha]", "[data-hcaptcha]", "#px-captcha",
]
CHALLENGE_WAIT_POLL_INTERVAL_MS = 2000
CHALLENGE_WAIT_TIMEOUT_MS = 300_000   # 5 minutes
CHALLENGE_HTTP_STATUSES = {403, 429}
```

Anti-fingerprinting applied in `_ensure_started()`:
- `headless=False`
- Launch arg: `--disable-blink-features=AutomationControlled`
- `context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")`
- No custom user-agent override (use the browser's real UA)

Page navigation: `page.goto(url, wait_until="networkidle", timeout=page_timeout_ms)`.

#### `src/asky/plugins/playwright_browser/plugin.py`

`PlaywrightBrowserPlugin(AskyPlugin)`:

**`activate(context: PluginContext)`:**
- Parse config dict into typed local attributes with defaults (see Step 6 for config schema).
- Instantiate `PlaywrightBrowserManager` with config values (lazy — browser not started yet).
- Register `FETCH_URL_OVERRIDE` hook: `context.hook_registry.register(FETCH_URL_OVERRIDE, self._on_fetch_url_override)`.

**`deactivate()`:**
- Call `self._browser_manager.close()`.

**`_on_fetch_url_override(ctx: FetchURLContext)`:**
1. Determine call-site identifier:
   ```python
   tc = ctx.trace_context or {}
   site = tc.get("tool_name") or tc.get("source", "")
   ```
2. If `site not in self._intercept`: return immediately (do not set `ctx.result`).
3. Try `html, final_url = self._browser_manager.fetch_page(ctx.url)`. On any exception: log warning, return (fallback activates).
4. Extract content: `trafilatura.extract(html, url=ctx.url, output_format=ctx.output_format, include_comments=False, include_tables=False)`. If `None`, use empty string.
5. Extract metadata: `trafilatura.extract_metadata(html)`.
6. If `ctx.include_links`: call `_extract_and_normalize_links(html, ctx.url, ctx.max_links)`.
7. Set `ctx.result` to:
   ```python
   {
       "error": None,
       "requested_url": ctx.url,
       "final_url": final_url,
       "content": content,
       "text": content,
       "title": (metadata.title or "")[:MAX_TITLE_CHARS] if metadata else "",
       "date": metadata.date if metadata else None,
       "links": links,
       "source": "playwright",
       "output_format": ctx.output_format,
       "page_type": "article",
   }
   ```

**`run_login_session(url: str)`:**
- Public method called from CLI.
- Calls `self._browser_manager.open_login_session(url)`.

### Step 6 — Default plugin config file

**File:** `src/asky/data/config/playwright_browser.toml`

```toml
browser = "chromium"

# Which call-site identifiers to intercept.
# Valid values: "get_url_content", "get_url_details", "shortlist", "research"
intercept = ["get_url_content", "get_url_details"]

# Random delay between consecutive requests to the same domain (ms).
same_site_min_delay_ms = 1500
same_site_max_delay_ms = 4000

# Save/restore cookies and localStorage between asky sessions.
persist_session = true

# Maximum time to wait for a page to load (ms).
page_timeout_ms = 30000

# Time with no network activity before page is considered done (ms).
network_idle_timeout_ms = 2000
```

### Step 7 — Register plugin in bundled `plugins.toml`

**File:** `src/asky/data/config/plugins.toml`

Add (disabled by default):
```toml
[plugin.playwright_browser]
enabled = false
module = "asky.plugins.playwright_browser.plugin"
class = "PlaywrightBrowserPlugin"
config_file = "plugins/playwright_browser.toml"
```

### Step 8 — Add `playwright` optional dependency

**File:** `pyproject.toml`

```toml
[project.optional-dependencies]
playwright = [
    "playwright>=1.40.0",
]
```

### Step 9 — Add `--playwright-login` to CLI

**File:** `src/asky/cli.py` (locate `main()` and the argparse setup).

1. Add argument:
   ```python
   parser.add_argument(
       "--playwright-login", metavar="URL", default=None,
       help="Open browser to URL for manual login; saves session for future fetches.",
   )
   ```

2. After plugin runtime is initialized, add early-exit branch:
   ```python
   if args.playwright_login:
       _run_playwright_login(args.playwright_login)
       return
   ```

3. Add helper (avoids circular import by using class name string):
   ```python
   def _run_playwright_login(url: str) -> None:
       from asky.plugins.runtime import get_or_create_plugin_runtime
       runtime = get_or_create_plugin_runtime()
       if runtime is None:
           print("Plugin runtime not available.", file=sys.stderr)
           sys.exit(1)
       for plugin in runtime.manager.plugins:
           if type(plugin).__name__ == "PlaywrightBrowserPlugin":
               plugin.run_login_session(url)
               return
       print("playwright_browser plugin is not enabled.", file=sys.stderr)
       sys.exit(1)
   ```

---

## Files Summary

| Action | File |
|--------|------|
| Modify | `src/asky/plugins/hook_types.py` |
| Modify | `src/asky/retrieval.py` |
| Modify | `src/asky/research/tools.py` |
| Modify | `pyproject.toml` |
| Modify | `src/asky/data/config/plugins.toml` |
| Modify | `src/asky/cli.py` |
| Create | `src/asky/plugins/playwright_browser/__init__.py` |
| Create | `src/asky/plugins/playwright_browser/plugin.py` |
| Create | `src/asky/plugins/playwright_browser/browser.py` |
| Create | `src/asky/data/config/playwright_browser.toml` |
| Create | `tests/test_playwright_browser_plugin.py` |

---

## Verification

### Automated tests (`tests/test_playwright_browser_plugin.py`)

Tests mock `PlaywrightBrowserManager.fetch_page` — no real browser launched.

1. **Hook registration**: activate plugin with mock config → `FETCH_URL_OVERRIDE` is in the registry.
2. **Intercept filtering — match**: `trace_context={"tool_name": "get_url_content"}`, `intercept=["get_url_content"]` → `ctx.result` is a dict.
3. **Intercept filtering — no match**: `trace_context={"tool_name": "shortlist"}`, `intercept=["get_url_content"]` → `ctx.result` is `None`.
4. **Fallback on Playwright error**: `fetch_page` raises → `ctx.result` stays `None` (requests/trafilatura will run).
5. **Result dict shape**: all required keys present (`error`, `content`, `text`, `title`, `date`, `links`, `source`, `output_format`, `page_type`, `final_url`, `requested_url`).
6. **Same-site delay logic**: consecutive calls to same domain call the sleep path; calls to different domains do not.
7. **`_try_fetch_url_plugin_override` returns None when runtime is None**: existing tests that don't initialize a runtime are unaffected.

### Regression check

```bash
uv run pytest -x -q
```

All existing tests must pass. The `_try_fetch_url_plugin_override` helper returns `None` when `get_or_create_plugin_runtime()` returns `None`, which is the case in all tests that don't set up a plugin runtime — zero behavioral change for the existing test suite.

### Manual integration test

```bash
uv pip install 'asky-cli[playwright]'
playwright install chromium
# Enable plugin in ~/.config/asky/plugins.toml
asky --playwright-login https://example.com   # verify browser opens, session saved
asky "summarize https://example.com"          # verify source="playwright" in verbose trace
```

---

## Final Checklist

- [ ] Type hints on all new functions
- [ ] No `print()` in library code — use `logger` or `sys.stderr` (CLI only)
- [ ] No magic numbers — all thresholds as module-level constants
- [ ] No process-narration comments
- [ ] Default config at `src/asky/data/config/playwright_browser.toml`
- [ ] Plugin disabled by default in bundled `plugins.toml`
- [ ] Existing test suite passes with no regressions
- [ ] New tests cover all 7 scenarios listed above
- [ ] DEVLOG.md updated
- [ ] ARCHITECTURE.md updated (new hook, new plugin, data-flow change in `retrieval.py`)
