"""Tests for token-bucket per-domain rate limiter."""

import os
import sys
import time
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "scripts"))

from _shared.rate_limiter import RateLimiter


@pytest.fixture()
def limiter(tmp_path):
    """Create a RateLimiter with known rates in a temp directory."""
    rates = {
        "fast.example.com": 10.0,
        "slow.example.com": 1.0,
        "sci-hub.*": 0.2,
        "_default": 2.0,
    }
    rl = RateLimiter(str(tmp_path), rate_limits=rates)
    yield rl
    rl.close()


# ---------------------------------------------------------------------------
# 1. Token bucket correctly limits requests
# ---------------------------------------------------------------------------

class TestTokenBucket:
    def test_first_request_returns_immediately(self, limiter):
        """First request to a domain should not block (bucket starts full)."""
        start = time.monotonic()
        limiter.wait("fast.example.com")
        elapsed = time.monotonic() - start
        # Should be near-instant (< 100ms)
        assert elapsed < 0.1

    def test_burst_capacity_is_2x_rate(self, limiter):
        """Burst allows 2x rate requests before blocking."""
        # slow.example.com: rate=1.0, max_tokens = max(1.0*2, 1.0) = 2.0
        # Should allow 2 requests without blocking
        start = time.monotonic()
        limiter.wait("slow.example.com")
        limiter.wait("slow.example.com")
        elapsed = time.monotonic() - start
        assert elapsed < 0.2  # Both should be near-instant

    def test_blocks_when_tokens_exhausted(self, limiter):
        """After exhausting tokens, wait() should block until refill."""
        # slow.example.com: rate=1.0, max_tokens=2.0
        # Drain all tokens
        limiter.wait("slow.example.com")
        limiter.wait("slow.example.com")
        # Third request should block for ~1 second (1 token / 1.0 RPS)
        # Use a mock to avoid actually sleeping
        with patch("_shared.rate_limiter.time.sleep") as mock_sleep, \
             patch("_shared.rate_limiter.random.random", return_value=0.5):
            limiter.wait("slow.example.com")
            # Should have slept at least once
            assert mock_sleep.called


# ---------------------------------------------------------------------------
# 2. Per-domain isolation
# ---------------------------------------------------------------------------

class TestPerDomainIsolation:
    def test_domains_have_independent_buckets(self, limiter):
        """Consuming tokens from one domain should not affect another."""
        # Drain slow.example.com
        limiter.wait("slow.example.com")
        limiter.wait("slow.example.com")
        # fast.example.com should still have full tokens
        start = time.monotonic()
        limiter.wait("fast.example.com")
        elapsed = time.monotonic() - start
        assert elapsed < 0.1

    def test_glob_pattern_matching(self, limiter):
        """Glob patterns (e.g., sci-hub.*) should match subdomains."""
        # sci-hub.* → rate 0.2, max_tokens = max(0.2*2, 1.0) = 1.0
        start = time.monotonic()
        limiter.wait("sci-hub.se")
        elapsed = time.monotonic() - start
        assert elapsed < 0.1  # First request from full bucket

    def test_default_rate_for_unknown_domain(self, limiter):
        """Unknown domains fall back to _default rate."""
        # _default = 2.0, max_tokens = max(2.0*2, 1.0) = 4.0
        start = time.monotonic()
        for _ in range(4):
            limiter.wait("unknown.example.com")
        elapsed = time.monotonic() - start
        assert elapsed < 0.2  # 4 burst tokens, all instant


# ---------------------------------------------------------------------------
# 3. Burst capacity
# ---------------------------------------------------------------------------

class TestBurst:
    def test_burst_minimum_one_token(self, limiter):
        """Even very slow rates get at least 1 token burst."""
        # sci-hub.*: rate=0.2, max_tokens = max(0.2*2, 1.0) = 1.0
        start = time.monotonic()
        limiter.wait("sci-hub.se")
        elapsed = time.monotonic() - start
        assert elapsed < 0.1

    def test_burst_does_not_exceed_max(self, limiter):
        """Tokens should not exceed max_tokens after refill."""
        conn = limiter._get_conn()
        limiter._ensure_bucket(conn, "slow.example.com")
        # Manually set last_refill far in the past to trigger large refill
        conn.execute(
            "UPDATE rate_limits SET last_refill = ?, tokens = 0 WHERE domain = ?",
            (time.time() - 1000, "slow.example.com"),
        )
        conn.commit()
        # After wait(), tokens should be capped at max_tokens (2.0) minus 1 consumed
        limiter.wait("slow.example.com")
        row = conn.execute(
            "SELECT tokens, max_tokens FROM rate_limits WHERE domain = ?",
            ("slow.example.com",),
        ).fetchone()
        assert row[0] <= row[1]  # tokens <= max_tokens


# ---------------------------------------------------------------------------
# 4. Refill timing
# ---------------------------------------------------------------------------

class TestRefillTiming:
    def test_tokens_refill_based_on_elapsed_time(self, limiter):
        """After draining tokens and waiting, tokens should refill."""
        conn = limiter._get_conn()
        limiter._ensure_bucket(conn, "slow.example.com")
        # Drain tokens and set last_refill 2 seconds ago
        conn.execute(
            "UPDATE rate_limits SET tokens = 0, last_refill = ? WHERE domain = ?",
            (time.time() - 2.0, "slow.example.com"),
        )
        conn.commit()
        # Now wait() should find refilled tokens (2 seconds * 1.0 RPS = 2.0 tokens)
        start = time.monotonic()
        limiter.wait("slow.example.com")
        elapsed = time.monotonic() - start
        assert elapsed < 0.1  # Should not block — tokens available from refill

    def test_backoff_sets_backoff_until(self, limiter):
        """backoff() should set backoff_until in the future."""
        limiter._ensure_bucket(limiter._get_conn(), "slow.example.com")
        with patch("_shared.rate_limiter.random.random", return_value=0.5):
            limiter.backoff("slow.example.com")
        conn = limiter._get_conn()
        row = conn.execute(
            "SELECT backoff_until FROM rate_limits WHERE domain = ?",
            ("slow.example.com",),
        ).fetchone()
        assert row[0] > time.time()  # backoff_until is in the future

    def test_backoff_zeroes_tokens(self, limiter):
        """backoff() should drain all tokens."""
        limiter.wait("slow.example.com")  # ensure bucket exists
        with patch("_shared.rate_limiter.random.random", return_value=0.5):
            limiter.backoff("slow.example.com")
        conn = limiter._get_conn()
        row = conn.execute(
            "SELECT tokens FROM rate_limits WHERE domain = ?",
            ("slow.example.com",),
        ).fetchone()
        assert row[0] == 0


# ---------------------------------------------------------------------------
# 5. Cross-invocation state persistence
# ---------------------------------------------------------------------------

class TestCrossInvocationState:
    def test_state_persists_across_instances(self, tmp_path):
        """A new RateLimiter instance should see state from a previous one."""
        rates = {"example.com": 1.0, "_default": 2.0}
        # First instance: drain tokens
        rl1 = RateLimiter(str(tmp_path), rate_limits=rates)
        rl1.wait("example.com")
        rl1.wait("example.com")
        rl1.close()

        # Second instance: should see depleted tokens
        rl2 = RateLimiter(str(tmp_path), rate_limits=rates)
        conn = rl2._get_conn()
        row = conn.execute(
            "SELECT tokens FROM rate_limits WHERE domain = ?",
            ("example.com",),
        ).fetchone()
        assert row is not None
        assert row[0] < 1.0  # Tokens should still be depleted
        rl2.close()

    def test_backoff_persists_across_instances(self, tmp_path):
        """Backoff state should survive across RateLimiter instances."""
        rates = {"example.com": 1.0, "_default": 2.0}
        rl1 = RateLimiter(str(tmp_path), rate_limits=rates)
        rl1.wait("example.com")
        with patch("_shared.rate_limiter.random.random", return_value=0.5):
            rl1.backoff("example.com")
        rl1.close()

        rl2 = RateLimiter(str(tmp_path), rate_limits=rates)
        conn = rl2._get_conn()
        row = conn.execute(
            "SELECT backoff_until FROM rate_limits WHERE domain = ?",
            ("example.com",),
        ).fetchone()
        assert row is not None
        assert row[0] > time.time()  # Backoff should still be active
        rl2.close()
