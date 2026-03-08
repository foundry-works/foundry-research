"""Tests for HTTP client retry logic, error handling, timeout, and User-Agent."""

from unittest.mock import MagicMock, patch

import requests

from _shared.http_client import HttpClient, _DEFAULT_UA, _RETRY_CODES, create_session


def _make_response(status_code, headers=None):
    """Create a mock requests.Response."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.headers = headers or {}
    return resp


def _make_client(tmp_path, **kwargs):
    """Create an HttpClient with mocked rate limiter to avoid real DB/sleeps."""
    client = HttpClient(session_dir=str(tmp_path), **kwargs)
    # Neuter rate limiter to avoid SQLite/sleep overhead in tests
    client._limiter.wait = MagicMock()
    client._limiter.backoff = MagicMock()
    return client


# ---------------------------------------------------------------------------
# 1. Retries on 429/500/503 with backoff
# ---------------------------------------------------------------------------

class TestRetryOnRetryableCodes:
    def test_retries_on_429(self, tmp_path):
        """429 triggers retry + rate limiter backoff."""
        client = _make_client(tmp_path, max_retries=2)
        mock_429 = _make_response(429)
        mock_200 = _make_response(200)

        with patch.object(client._session, "request", side_effect=[mock_429, mock_200]), \
             patch("_shared.http_client.time.sleep"):
            resp = client.get("https://api.example.com/test")

        assert resp.status_code == 200
        client._limiter.backoff.assert_called_once()

    def test_retries_on_500(self, tmp_path):
        """500 triggers retry."""
        client = _make_client(tmp_path, max_retries=2)
        mock_500 = _make_response(500)
        mock_200 = _make_response(200)

        with patch.object(client._session, "request", side_effect=[mock_500, mock_200]), \
             patch("_shared.http_client.time.sleep"):
            resp = client.get("https://api.example.com/test")

        assert resp.status_code == 200

    def test_retries_on_503(self, tmp_path):
        """503 triggers retry."""
        client = _make_client(tmp_path, max_retries=2)
        mock_503 = _make_response(503)
        mock_200 = _make_response(200)

        with patch.object(client._session, "request", side_effect=[mock_503, mock_200]), \
             patch("_shared.http_client.time.sleep"):
            resp = client.get("https://api.example.com/test")

        assert resp.status_code == 200

    def test_returns_last_response_after_max_retries(self, tmp_path):
        """After exhausting retries, returns the last error response."""
        client = _make_client(tmp_path, max_retries=2)
        mock_429 = _make_response(429)

        with patch.object(client._session, "request", return_value=mock_429), \
             patch("_shared.http_client.time.sleep"):
            resp = client.get("https://api.example.com/test")

        assert resp.status_code == 429

    def test_retry_codes_set(self):
        """Verify the retry codes set includes expected status codes."""
        assert 429 in _RETRY_CODES
        assert 500 in _RETRY_CODES
        assert 502 in _RETRY_CODES
        assert 503 in _RETRY_CODES
        assert 404 not in _RETRY_CODES

    def test_retry_after_header_respected(self, tmp_path):
        """Retry-After header controls sleep duration."""
        client = _make_client(tmp_path, max_retries=2)
        mock_429 = _make_response(429, headers={"Retry-After": "5"})
        mock_200 = _make_response(200)

        with patch.object(client._session, "request", side_effect=[mock_429, mock_200]), \
             patch("_shared.http_client.time.sleep") as mock_sleep:
            client.get("https://api.example.com/test")

        # Should have slept for min(5.0, 30.0) = 5.0
        mock_sleep.assert_called_with(5.0)


# ---------------------------------------------------------------------------
# 2. No retry on 404
# ---------------------------------------------------------------------------

class TestNoRetryOn404:
    def test_404_returns_immediately(self, tmp_path):
        """404 should return immediately without retry."""
        client = _make_client(tmp_path, max_retries=3)
        mock_404 = _make_response(404)

        with patch.object(client._session, "request", return_value=mock_404) as mock_req:
            resp = client.get("https://api.example.com/missing")

        assert resp.status_code == 404
        assert mock_req.call_count == 1  # No retries
        client._limiter.backoff.assert_not_called()

    def test_other_client_errors_no_retry(self, tmp_path):
        """Other 4xx errors (401, 403) also don't retry."""
        client = _make_client(tmp_path, max_retries=3)

        for code in (401, 403, 422):
            mock_resp = _make_response(code)
            with patch.object(client._session, "request", return_value=mock_resp) as mock_req:
                resp = client.get("https://api.example.com/test")
            assert resp.status_code == code
            assert mock_req.call_count == 1


# ---------------------------------------------------------------------------
# 3. Timeout handling
# ---------------------------------------------------------------------------

class TestTimeoutHandling:
    def test_default_timeout_set(self, tmp_path):
        """Default timeout is (15, 30) for connect and read."""
        client = _make_client(tmp_path)
        mock_200 = _make_response(200)

        with patch.object(client._session, "request", return_value=mock_200) as mock_req:
            client.get("https://api.example.com/test")

        _, kwargs = mock_req.call_args
        assert kwargs["timeout"] == (15, 30)

    def test_custom_timeout_override(self, tmp_path):
        """Caller can override timeout."""
        client = _make_client(tmp_path)
        mock_200 = _make_response(200)

        with patch.object(client._session, "request", return_value=mock_200) as mock_req:
            client.get("https://api.example.com/test", timeout=(5, 10))

        _, kwargs = mock_req.call_args
        assert kwargs["timeout"] == (5, 10)

    def test_request_exception_retried(self, tmp_path):
        """Network-level exceptions are retried."""
        client = _make_client(tmp_path, max_retries=2)
        mock_200 = _make_response(200)

        with patch.object(
            client._session, "request",
            side_effect=[requests.ConnectionError("timeout"), mock_200],
        ), patch("_shared.http_client.time.sleep"):
            resp = client.get("https://api.example.com/test")

        assert resp.status_code == 200

    def test_request_exception_raises_after_max_retries(self, tmp_path):
        """Network exceptions raise after exhausting retries."""
        client = _make_client(tmp_path, max_retries=1)

        with patch.object(
            client._session, "request",
            side_effect=requests.ConnectionError("refused"),
        ), patch("_shared.http_client.time.sleep"):
            with __import__("pytest").raises(requests.ConnectionError):
                client.get("https://api.example.com/test")


# ---------------------------------------------------------------------------
# 4. User-Agent sent correctly
# ---------------------------------------------------------------------------

class TestUserAgent:
    def test_default_user_agent(self, tmp_path):
        """Default User-Agent header is set."""
        client = _make_client(tmp_path)
        assert client._session.headers["User-Agent"] == _DEFAULT_UA

    def test_custom_user_agent(self, tmp_path):
        """Custom User-Agent can be set via create_session."""
        client = create_session(str(tmp_path), user_agent="custom-agent/2.0")
        assert client._session.headers["User-Agent"] == "custom-agent/2.0"
        client.close()

    def test_user_agent_contains_tool_name(self):
        """Default UA identifies as deep-research."""
        assert "deep-research" in _DEFAULT_UA


# ---------------------------------------------------------------------------
# 5. POST method works same as GET
# ---------------------------------------------------------------------------

class TestPostMethod:
    def test_post_uses_same_retry_logic(self, tmp_path):
        """POST requests use the same retry logic as GET."""
        client = _make_client(tmp_path, max_retries=2)
        mock_503 = _make_response(503)
        mock_200 = _make_response(200)

        with patch.object(client._session, "request", side_effect=[mock_503, mock_200]) as mock_req, \
             patch("_shared.http_client.time.sleep"):
            resp = client.post("https://api.example.com/data", json={"key": "value"})

        assert resp.status_code == 200
        # Verify it was called with POST method
        assert mock_req.call_args_list[0][0][0] == "POST"
