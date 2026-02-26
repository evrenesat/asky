# Playwright Browser Plugin — Agent Guide

This plugin provides a Playwright-based retrieval backend for `fetch_url_document`. It is designed to bypass aggressive bot protection by using a real, non-headless browser.

## Architecture

### `browser.py` (`PlaywrightBrowserManager`)
The core browser controller.
- **Lazy Initialization**: Browser only starts on the first `fetch_page` or `open_login_session` call.
- **Session Persistence**: Saves/loads `storage_state` (cookies/localStorage) to `playwright_session.json` in the plugin's data directory.
- **Anti-Fingerprinting**: 
  - Runs in **headed** mode (`headless=False`) to avoid headless-detection scripts.
  - Disables `AutomationControlled` blink features.
  - Overrides `navigator.webdriver` via init scripts.
- **Challenge Handling**: Detects Cloudflare/hCaptcha/ReCaptcha and pauses execution, prompting the user via `stderr` to solve it in the visible window.
- **Concurrency**: Uses a `threading.Lock` to serialize browser access, preventing race conditions and reducing detection risk from parallel requests.

### `plugin.py` (`PlaywrightBrowserPlugin`)
The glue between the Asky plugin system and the browser manager.
- **Hook**: Intercepts `FETCH_URL_OVERRIDE`.
- **Filtering**: Only intercepts requests where the `trace_context` includes a `tool_name` or `source` present in the `intercept` configuration list.
- **Fallback**: If Playwright fails (crash, timeout), it logs a warning and leaves `ctx.result` as `None`, allowing the standard `requests`/`trafilatura` pipeline to take over.

## Call-Site Identifiers
When calling `fetch_url_document`, the `trace_context` determines if this plugin will intercept:
- `get_url_content` / `get_url_details`: standard chat tools.
- `research`: research mode tools (`extract_links`, `get_relevant_content`, etc.).
- `shortlist`: the pre-LLM source ranking stage.

## Troubleshooting
- **No interception**: Check if the call-site is in the `intercept` config list.
- **Browser won't start**: Ensure `playwright` is installed (`uv pip install 'asky-cli[playwright]'`) and browser binaries are present (`playwright install chromium`).
- **Detection**: Some sites may still detect automation. Try using `--playwright-login` to establish a "real" session first.
