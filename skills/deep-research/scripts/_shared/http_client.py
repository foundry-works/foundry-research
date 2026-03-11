"""Shared HTTP client with rate limiting, retries, and User-Agent management."""

import time
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from _shared.rate_limiter import RateLimiter

# Default timeouts (seconds)
_CONNECT_TIMEOUT = 15
_READ_TIMEOUT = 30

# Default User-Agent
_DEFAULT_UA = "deep-research/1.0 (academic research tool; +https://github.com/anthropics/claude-code)"

# Status codes that trigger retry with backoff
_RETRY_CODES = {429, 500, 502, 503}


def create_session(
    session_dir: str,
    user_agent: str | None = None,
    rate_limits: dict[str, float] | None = None,
    max_retries: int = 3,
) -> "HttpClient":
    """Create a configured HTTP client session.

    Args:
        session_dir: Path to session directory for rate limiter state.
        user_agent: Custom User-Agent string. Defaults to deep-research UA.
        rate_limits: Override default per-domain rate limits.
        max_retries: Max retry attempts on retryable errors.
    """
    return HttpClient(
        session_dir=session_dir,
        user_agent=user_agent or _DEFAULT_UA,
        rate_limits=rate_limits,
        max_retries=max_retries,
    )


class HttpClient:
    """HTTP client wrapping requests.Session with rate limiting and retries.

    Features:
    - Automatic rate limiter integration (waits before each request)
    - Retry with exponential backoff on 429/500/502/503
    - No retry on 404 or other client errors
    - Configurable User-Agent header
    - Connection pooling via requests.Session
    """

    def __init__(
        self,
        session_dir: str,
        user_agent: str = _DEFAULT_UA,
        rate_limits: dict[str, float] | None = None,
        max_retries: int = 3,
    ):
        self._limiter = RateLimiter(session_dir=session_dir, rate_limits=rate_limits)
        self._max_retries = max_retries

        self._session = requests.Session()
        self._session.headers["User-Agent"] = user_agent

        # Connection-level retries for network errors (not HTTP status retries)
        adapter = HTTPAdapter(
            max_retries=Retry(total=2, backoff_factor=0.5, status_forcelist=[]),
        )
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def get(self, url: str, **kwargs) -> requests.Response:
        """Send a GET request with rate limiting and retries."""
        return self._request("GET", url, **kwargs)

    def head(self, url: str, **kwargs) -> requests.Response:
        """Send a HEAD request with rate limiting and retries."""
        return self._request("HEAD", url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        """Send a POST request with rate limiting and retries."""
        return self._request("POST", url, **kwargs)

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Execute a request with rate limiting and retry logic."""
        domain = urlparse(url).hostname or ""
        kwargs.setdefault("timeout", (_CONNECT_TIMEOUT, _READ_TIMEOUT))

        last_exc: Exception | None = None

        for attempt in range(self._max_retries + 1):
            self._limiter.wait(domain)

            try:
                response = self._session.request(method, url, **kwargs)
            except requests.RequestException as e:
                last_exc = e
                if attempt < self._max_retries:
                    time.sleep(2 ** attempt)
                    continue
                raise

            if response.status_code not in _RETRY_CODES:
                return response

            # Retryable status — signal backoff and retry
            self._limiter.backoff(domain)

            if attempt < self._max_retries:
                # Check for Retry-After header
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait = float(retry_after)
                    except ValueError:
                        wait = 2 ** attempt
                else:
                    wait = 2 ** attempt
                time.sleep(min(wait, 30.0))
            else:
                return response

        # Should not reach here, but satisfy type checker
        if last_exc:
            raise last_exc
        raise requests.RequestException(f"Max retries exceeded for {url}")

    @property
    def session(self) -> requests.Session:
        """Access the underlying requests.Session for advanced usage."""
        return self._session

    def close(self) -> None:
        """Close the HTTP session and rate limiter."""
        self._session.close()
        self._limiter.close()
