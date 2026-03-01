# Playwright Browser Plugin

The Playwright Browser plugin allows `asky` to use a real, visible browser (Chromium by default, with support for Firefox and WebKit) to fetch web pages. This is highly effective for:

- Bypassing bot protection (Cloudflare, CAPTCHAs).
- Accessing sites that require JavaScript rendering.
- Using authenticated sessions (logging in once and staying logged in).

## Installation

1. Install the optional dependency:
   ```bash
   uv pip install 'asky-cli[playwright]'
   ```
2. The chosen browser binary (Chromium by default) will be **installed automatically** on its first use. If you prefer to install it manually beforehand, run:
   ```bash
   playwright install chromium
   ```

## Configuration

Enable the plugin in your `~/.config/asky/plugins.toml`:

```toml
[plugin.playwright_browser]
enabled = true
module = "asky.plugins.playwright_browser.plugin"
class = "PlaywrightBrowserPlugin"
config_file = "plugins/playwright_browser.toml"
```

### Advanced Settings

Edit `~/.config/asky/plugins/playwright_browser.toml` to customize behavior:

```toml
# The browser engine to use. Options: "chromium", "firefox", "webkit"
browser = "chromium"

# Which tools should use the browser.
# Options: "get_url_content", "get_url_details", "research", "shortlist", "default"
intercept = ["get_url_content", "get_url_details", "research", "shortlist", "default"]

# Wait after page load for SPAs and dynamic sites to render their content
post_load_delay_ms = 2000

# Keep the browser open between fetches to speed up subsequent requests.
# If true, it reuses a single tab to prevent tab accumulation.
keep_browser_open = true

# Delay between requests to the same site (prevents rate limiting)
same_site_min_delay_ms = 1500
same_site_max_delay_ms = 4000

# Persist cookies and login state
persist_session = true
```

## Usage

### Handling CAPTCHAs

When the plugin is active, it runs in **non-headless** mode. If a site presents a CAPTCHA or Cloudflare challenge:

1. The browser window will pop up.
2. Solve the challenge manually in the window.
3. `asky` will detect the resolution and automatically continue.

### Persistent Login

If a site requires you to be logged in:

1. Run: `asky --browser https://example.com`
2. Perform the login in the browser window.
3. Press **Enter** in your terminal to save the session.
4. Future requests to that site will now use your logged-in cookies.

## Fallback Behavior

If Playwright fails to load a page for any reason (e.g., the browser crashes or times out), `asky` will automatically fall back to its standard retrieval method (`requests`) to ensure you still get an answer.
