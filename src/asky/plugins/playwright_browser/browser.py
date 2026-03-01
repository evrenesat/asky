"""Sync Playwright browser manager with session persistence and CAPTCHA handling."""

from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

try:
    from playwright.sync_api import (
        Browser,
        BrowserContext,
        Page,
        TimeoutError,
        sync_playwright,
    )
except ImportError:
    sync_playwright = None  # type: ignore
    TimeoutError = Exception  # type: ignore

logger = logging.getLogger(__name__)

CHALLENGE_SELECTORS = [
    ".cf-challenge",
    "#challenge-form",
    "[data-recaptcha]",
    "[data-hcaptcha]",
    "#px-captcha",
]
CHALLENGE_WAIT_POLL_INTERVAL_MS = 2000
CHALLENGE_WAIT_TIMEOUT_MS = 300_000
CHALLENGE_HTTP_STATUSES = {403, 429}
CHALLENGE_URL_PATTERNS = [
    "/cdn-cgi/challenge-platform/",
    "checkpoint/challenge",
]


class PlaywrightBrowserManager:
    """Manages a lazy-started Playwright browser instance with session persistence."""

    def __init__(
        self,
        data_dir: Path,
        browser_type: str = "chromium",
        persist_session: bool = True,
        same_site_min_delay_ms: int = 1500,
        same_site_max_delay_ms: int = 4000,
        page_timeout_ms: int = 30000,
        network_idle_timeout_ms: int = 2000,
        keep_browser_open: bool = True,
        post_load_delay_ms: int = 2000,
    ) -> None:
        self._data_dir = data_dir
        self._browser_type = browser_type
        self._persist_session = persist_session
        self._same_site_min_delay_ms = same_site_min_delay_ms
        self._same_site_max_delay_ms = same_site_max_delay_ms
        self._page_timeout_ms = page_timeout_ms
        self._network_idle_timeout_ms = network_idle_timeout_ms
        self._keep_browser_open = keep_browser_open
        self._post_load_delay_ms = post_load_delay_ms

        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._lock = Lock()
        self._last_request_time: Dict[str, float] = {}

    def _ensure_started(self) -> None:
        if self._context is not None:
            return

        if sync_playwright is None:
            raise ImportError(
                "Playwright not installed. Run 'uv pip install asky-cli[playwright]' "
                "and 'playwright install chromium'."
            )

        self._playwright = sync_playwright().start()
        browser_launcher = getattr(self._playwright, self._browser_type)

        launch_args: Dict[str, Any] = {"headless": False}
        if self._browser_type == "chromium":
            launch_args["args"] = ["--disable-blink-features=AutomationControlled"]

        def _launch() -> None:
            if self._persist_session:
                user_data_dir = (
                    self._data_dir / f"playwright_profile_{self._browser_type}"
                )
                user_data_dir.mkdir(parents=True, exist_ok=True)
                self._context = browser_launcher.launch_persistent_context(
                    user_data_dir=str(user_data_dir), **launch_args
                )
            else:
                self._browser = browser_launcher.launch(**launch_args)
                self._context = self._browser.new_context()

        try:
            _launch()
        except Exception as e:
            error_msg = str(e)
            if (
                "Executable doesn't exist at" in error_msg
                or "playwright install" in error_msg
            ):
                import sys
                import subprocess

                logger.info(
                    "Playwright browser %s missing. Attempting automatic installation...",
                    self._browser_type,
                )
                try:
                    from rich.console import Console

                    console = Console()
                    console.print(
                        f"\n[bold yellow]Playwright Plugin:[/bold yellow] Installing [cyan]{self._browser_type}[/cyan] browser... this may take a minute."
                    )
                except ImportError:
                    print(
                        f"\n[Playwright Plugin] Installing {self._browser_type} browser... this may take a minute.",
                        file=sys.stderr,
                    )

                try:
                    subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "playwright",
                            "install",
                            self._browser_type,
                        ],
                        check=True,
                    )
                    try:
                        Console().print(
                            f"[bold green]Playwright Plugin:[/bold green] Successfully installed [cyan]{self._browser_type}[/cyan]."
                        )
                    except ImportError:
                        print(
                            f"[Playwright Plugin] Successfully installed {self._browser_type}.",
                            file=sys.stderr,
                        )

                    # Retry launch after installation
                    _launch()
                except subprocess.CalledProcessError as install_err:
                    raise RuntimeError(
                        f"Failed to automatically install Playwright browser: {install_err}"
                    ) from e
            else:
                raise

        if self._context is not None:
            self._context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

    def _apply_delay(self, url: str) -> None:
        netloc = urlparse(url).netloc
        if not netloc:
            return

        if netloc not in self._last_request_time:
            self._last_request_time[netloc] = time.perf_counter()
            return

        last_time = self._last_request_time.get(netloc, 0)
        elapsed = (time.perf_counter() - last_time) * 1000

        delay = random.randint(
            self._same_site_min_delay_ms, self._same_site_max_delay_ms
        )
        if elapsed < delay:
            sleep_time = (delay - elapsed) / 1000
            logger.debug("Applying same-site delay for %s: %.2fs", netloc, sleep_time)
            time.sleep(sleep_time)

        self._last_request_time[netloc] = time.perf_counter()

    def _detect_challenge(
        self, page: Page, response_status: Optional[int]
    ) -> Optional[str]:
        if response_status in CHALLENGE_HTTP_STATUSES:
            return f"HTTP status {response_status}"

        current_url = page.url
        for pattern in CHALLENGE_URL_PATTERNS:
            if pattern in current_url:
                return f"Challenge URL pattern '{pattern}' detected"

        for selector in CHALLENGE_SELECTORS:
            try:
                if page.locator(selector).count() > 0:
                    return f"Selector '{selector}' found"
            except Exception as e:
                logger.debug("Playwright challenge selector check failed: %s", e)
                continue
        return None

    def _wait_for_challenge_resolution(self, page: Page, initial_reason: str) -> None:
        logger.warning(
            "Challenge detected on %s (Reason: %s). Please solve it in the browser window.",
            page.url,
            initial_reason,
        )

        start_time = time.perf_counter()
        while (time.perf_counter() - start_time) * 1000 < CHALLENGE_WAIT_TIMEOUT_MS:
            time.sleep(CHALLENGE_WAIT_POLL_INTERVAL_MS / 1000)
            if not self._detect_challenge(page, None):
                logger.info("Challenge resolved.")
                return

        logger.warning("Challenge resolution timed out.")

    def fetch_page(self, url: str) -> Tuple[str, str]:
        with self._lock:
            self._ensure_started()
            self._apply_delay(url)

            if not self._context:
                raise RuntimeError("Browser context not initialized")

            if self._keep_browser_open and self._context.pages:
                page = self._context.pages[-1]
            else:
                page = self._context.new_page()

            try:
                logger.debug("Playwright navigating to: %s", url)
                # Use 'domcontentloaded' instead of 'networkidle' to avoid hanging on
                # infinite background requests (ads, tracking, video players)
                response = page.goto(
                    url, wait_until="domcontentloaded", timeout=self._page_timeout_ms
                )

                # Give SPAs and dynamic sites a moment to render their main content
                page.wait_for_timeout(self._post_load_delay_ms)

                status = response.status if response else None
                challenge_reason = self._detect_challenge(page, status)

                if challenge_reason:
                    self._wait_for_challenge_resolution(page, challenge_reason)
                    try:
                        page.wait_for_load_state(
                            "domcontentloaded", timeout=self._page_timeout_ms
                        )
                        page.wait_for_timeout(self._post_load_delay_ms)
                    except (TimeoutError, Exception) as e:
                        logger.debug(
                            "Post-challenge load state wait failed/timed out: %s", e
                        )

                html = page.content()
                final_url = page.url

                logger.debug(
                    "Playwright fetched final_url=%s status=%s title='%s' content_length=%d",
                    final_url,
                    status,
                    page.title(),
                    len(html),
                )

                return html, final_url
            except Exception as e:
                logger.debug("Playwright fetch failed for %s. Error: %s", url, e)
                raise
            finally:
                if not self._keep_browser_open:
                    page.close()
                    self._close_unlocked()

    def open_login_session(self, url: str) -> None:
        from asky.daemon.launch_context import is_interactive

        if not is_interactive():
            raise RuntimeError(
                "open_login_session (input()) called in non-interactive context"
            )

        with self._lock:
            self._ensure_started()
            if not self._context:
                return

            url = url.strip()
            if url.startswith("https//"):
                url = url.replace("https//", "https://", 1)
            elif url.startswith("http//"):
                url = url.replace("http//", "http://", 1)
            elif not url.startswith("http://") and not url.startswith("https://"):
                url = f"https://{url}"

            if self._keep_browser_open and self._context.pages:
                page = self._context.pages[-1]
            else:
                page = self._context.new_page()

            try:
                logger.info("Opening %s for manual login.", url)
                logger.info(
                    "Please log in and then press ENTER in this terminal to save the session."
                )
                page.goto(url)
                input()
                logger.info("Session saved.")
            except Exception as e:
                import sys

                print(
                    f"\n[Playwright Plugin] Failed to open login session for '{url}': {e}",
                    file=sys.stderr,
                )
            finally:
                if not self._keep_browser_open:
                    page.close()
                    self._close_unlocked()

    def close(self) -> None:
        with self._lock:
            self._close_unlocked()

    def _close_unlocked(self) -> None:
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self._browser = None
        self._context = None
        self._playwright = None
