"""HTTP client with rate limiting, retries, and block detection."""
from __future__ import annotations

import logging
import random
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class BlockedError(RuntimeError):
    """Raised when Douban blocks the request (403 or redirect to a verification page)."""


class PoliteClient:
    """Wait randomly before each request, retry failures, and raise BlockedError when blocked."""

    def __init__(
        self,
        min_delay: float = 2.0,
        max_delay: float = 5.0,
        cookie: str | None = None,
        timeout: float = 15.0,
        retries: int = 3,
    ) -> None:
        if min_delay > max_delay:
            raise ValueError("min_delay cannot be greater than max_delay")

        self.min_delay = min_delay
        self.max_delay = max_delay
        self.timeout = timeout
        self._last_request = 0.0

        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": DEFAULT_UA, "Accept-Language": "zh-CN,zh;q=0.9"}
        )

        if cookie:
            self.session.headers["Cookie"] = cookie

        # Apply a Retry strategy through HTTPAdapter.
        # Use exponential backoff for 429 and 5xx responses.
        retry = Retry(
            total=retries,
            backoff_factor=2,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def _wait(self) -> None:
        delay = random.uniform(self.min_delay, self.max_delay)
        elapsed = time.monotonic() - self._last_request

        if elapsed < delay:
            time.sleep(delay - elapsed)

        self._last_request = time.monotonic()

    def get(self, url: str) -> str:
        self._wait()
        log.debug("GET %s", url)
        resp = self.session.get(url, timeout=self.timeout)

        if "sec.douban.com" in resp.url:
            raise BlockedError(
                f"Douban browser verification triggered: {url}\n"
                "Please log in to Douban in a browser and provide the Cookie "
                "through the DOUBAN_COOKIE environment variable."
            )

        if resp.status_code == 403:
            raise BlockedError(f"Request rejected (403): {url}")

        resp.raise_for_status()
        resp.encoding = "utf-8"
        return resp.text