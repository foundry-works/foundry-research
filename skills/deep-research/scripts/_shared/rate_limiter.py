"""Token-bucket per-domain rate limiter backed by SQLite for cross-process safety."""

import fnmatch
import random
import sqlite3
import threading
import time
from pathlib import Path

from _shared.config import RATE_LIMITS


class RateLimiter:
    """Per-domain token-bucket rate limiter with SQLite persistence.

    Uses SQLite WAL mode for concurrent access across processes.
    No manual lock management needed — SQLite handles its own locking.

    Args:
        session_dir: Path to session directory containing state.db.
        rate_limits: Override default rate limits dict. Keys are domain names
                     (or glob patterns like "sci-hub.*"), values are requests/sec.
    """

    def __init__(self, session_dir: str, rate_limits: dict[str, float] | None = None):
        self._rates = rate_limits or dict(RATE_LIMITS)
        self._db_path = Path(session_dir) / "state.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a thread-local database connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(str(self._db_path), timeout=20)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=20000")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        """Create rate limit tracking table if it doesn't exist."""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rate_limits (
                domain TEXT PRIMARY KEY,
                tokens REAL NOT NULL,
                max_tokens REAL NOT NULL,
                refill_rate REAL NOT NULL,
                last_refill REAL NOT NULL,
                backoff_until REAL NOT NULL DEFAULT 0
            )
        """)
        conn.commit()

    def _get_rate(self, domain: str) -> float:
        """Look up rate limit for a domain, supporting glob patterns."""
        if domain in self._rates:
            return self._rates[domain]
        # Try glob patterns (e.g., "sci-hub.*")
        for pattern, rate in self._rates.items():
            if "*" in pattern and fnmatch.fnmatch(domain, pattern):
                return rate
        return self._rates.get("_default", 2.0)

    def _ensure_bucket(self, conn: sqlite3.Connection, domain: str) -> None:
        """Create a bucket row for the domain if it doesn't exist."""
        rate = self._get_rate(domain)
        max_tokens = max(rate * 2, 1.0)  # burst = 2x rate, minimum 1 token
        conn.execute(
            """INSERT OR IGNORE INTO rate_limits (domain, tokens, max_tokens, refill_rate, last_refill, backoff_until)
               VALUES (?, ?, ?, ?, ?, 0)""",
            (domain, max_tokens, max_tokens, rate, time.time()),
        )

    def wait(self, domain: str) -> None:
        """Block until it's safe to make a request to the given domain.

        Refills tokens based on elapsed time, then consumes one token.
        If no tokens available, sleeps until one is refilled.
        Also respects backoff_until from previous 429/503 responses.

        Uses BEGIN IMMEDIATE + single UPDATE to atomically check-and-decrement
        tokens, preventing concurrent processes from double-consuming.
        """
        while True:
            conn = self._get_conn()
            self._ensure_bucket(conn, domain)

            now = time.time()

            # Check backoff first (read-only, no race concern)
            row = conn.execute(
                "SELECT refill_rate, backoff_until FROM rate_limits WHERE domain = ?",
                (domain,),
            ).fetchone()

            if row is None:
                return  # shouldn't happen after ensure_bucket

            refill_rate, backoff_until = row

            # Respect backoff from 429/503
            if now < backoff_until:
                wait_time = backoff_until - now
                # Full jitter [50%-150%] to spread concurrent processes
                wait_time *= 0.5 + random.random()
                time.sleep(wait_time)
                continue

            # Atomic token refill + consume: commit any implicit transaction first,
            # then BEGIN IMMEDIATE to take a write lock so no other process can
            # read stale tokens between our refill calculation and the decrement.
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """UPDATE rate_limits
                   SET tokens = MIN(max_tokens, tokens + (? - last_refill) * refill_rate) - 1.0,
                       last_refill = ?
                   WHERE domain = ?
                     AND MIN(max_tokens, tokens + (? - last_refill) * refill_rate) >= 1.0""",
                (now, now, domain, now),
            )
            changed = conn.execute("SELECT changes()").fetchone()[0]
            conn.commit()

            if changed:
                return

            # Not enough tokens — estimate wait time
            wait_time = 1.0 / refill_rate
            # Full jitter [50%-150%] to spread concurrent processes
            wait_time *= 0.5 + random.random()
            time.sleep(wait_time)

    def backoff(self, domain: str) -> None:
        """Signal a rate limit hit (429/503). Applies exponential backoff.

        Backoff sequence: 2s → 4s → 8s → 16s → 30s cap.
        Adds ±20% jitter to avoid thundering herd.
        """
        conn = self._get_conn()
        self._ensure_bucket(conn, domain)

        row = conn.execute(
            "SELECT backoff_until FROM rate_limits WHERE domain = ?",
            (domain,),
        ).fetchone()

        now = time.time()
        if row and row[0] > now:
            # Already backing off — double the remaining time
            remaining = row[0] - now
            delay = min(remaining * 2, 30.0)
        else:
            delay = 2.0

        # Cap at 30 seconds
        delay = min(delay, 30.0)
        # Full jitter [50%-150%] to spread concurrent processes
        delay *= 0.5 + random.random()

        conn.execute(
            "UPDATE rate_limits SET backoff_until = ?, tokens = 0 WHERE domain = ?",
            (now + delay, domain),
        )
        conn.commit()

    def close(self) -> None:
        """Close the thread-local database connection."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None
