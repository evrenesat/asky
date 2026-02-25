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
    from playwright.sync_api import Browser, BrowserContext, Page, TimeoutError, sync_playwright
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
    ) -> None:
        self._data_dir = data_dir
        self._browser_type = browser_type
        self._persist_session = persist_session
        self._same_site_min_delay_ms = same_site_min_delay_ms
        self._same_site_max_delay_ms = same_site_max_delay_ms
        self._page_timeout_ms = page_timeout_ms
        self._network_idle_timeout_ms = network_idle_timeout_ms

        self._session_path = self._data_dir / "playwright_session.json"
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._lock = Lock()
        self._last_request_time: Dict[str, float] = {}

    def _ensure_started(self) -> None:
        if self._browser is not None:
            return

        if sync_playwright is None:
            raise ImportError(
                "Playwright not installed. Run 'uv pip install asky-cli[playwright]' "
                "and 'playwright install chromium'."
            )

        self._playwright = sync_playwright().start()
        browser_launcher = getattr(self._playwright, self._browser_type)

        self._browser = browser_launcher.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )

        context_kwargs: Dict[str, Any] = {}
        if self._persist_session and self._session_path.exists():
            try:
                with open(self._session_path, "r", encoding="utf-8") as f:
                    context_kwargs["storage_state"] = json.load(f)
            except Exception as e:
                logger.warning("Failed to load Playwright session: %s", e)

        self._context = self._browser.new_context(**context_kwargs)

        self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

    def _save_session(self) -> None:
        if self._context and self._persist_session:
            try:
                self._data_dir.mkdir(parents=True, exist_ok=True)
                state = self._context.storage_state()
                with open(self._session_path, "w", encoding="utf-8") as f:
                    json.dump(state, f)
            except Exception as e:
                logger.warning("Failed to save Playwright session: %s", e)

    def _apply_delay(self, url: str) -> None:
        netloc = urlparse(url).netloc
        if not netloc:
            return

        if netloc not in self._last_request_time:
            self._last_request_time[netloc] = time.perf_counter()
            return

        last_time = self._last_request_time.get(netloc, 0)
        elapsed = (time.perf_counter() - last_time) * 1000

        delay = random.randint(self._same_site_min_delay_ms, self._same_site_max_delay_ms)
        if elapsed < delay:
            sleep_time = (delay - elapsed) / 1000
            logger.debug("Applying same-site delay for %s: %.2fs", netloc, sleep_time)
            time.sleep(sleep_time)

        self._last_request_time[netloc] = time.perf_counter()

    def _detect_challenge(self, page: Page, response_status: Optional[int]) -> bool:
        if response_status in CHALLENGE_HTTP_STATUSES:
            return True

        for selector in CHALLENGE_SELECTORS:
            try:
                if page.locator(selector).count() > 0:
                    return True
            except Exception as e:
                logger.debug("Playwright challenge selector check failed: %s", e)
                continue
        return False

    def _wait_for_challenge_resolution(self, page: Page) -> None:
        logger.warning(
            "Challenge detected on %s. Please solve it in the browser window.",
            page.url,
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

            page = self._context.new_page()
            try:
                response = page.goto(
                    url, wait_until="networkidle", timeout=self._page_timeout_ms
                )

                status = response.status if response else None
                if self._detect_challenge(page, status):
                    self._wait_for_challenge_resolution(page)
                    try:
                        page.wait_for_load_state(
                            "networkidle", timeout=self._network_idle_timeout_ms
                        )
                    except (TimeoutError, Exception) as e:
                        logger.debug("Post-challenge load state wait failed/timed out: %s", e)

                html = page.content()
                final_url = page.url
                self._save_session()
                return html, final_url
            finally:
                page.close()

    def open_login_session(self, url: str) -> None:
        with self._lock:
            self._ensure_started()
            if not self._context:
                return

            page = self._context.new_page()
            try:
                logger.info("Opening %s for manual login.", url)
                logger.info("Please log in and then press ENTER in this terminal to save the session.")
                page.goto(url)
                input()
                self._save_session()
                logger.info("Session saved.")
            finally:
                page.close()

    def close(self) -> None:
        with self._lock:
            if self._context:
                self._save_session()
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
            self._browser = None
            self._context = None
            self._playwright = None
