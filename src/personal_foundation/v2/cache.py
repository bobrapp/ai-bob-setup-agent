"""LLM response cache — reduces cost by caching identical prompts.

Uses SQLite (same DB) for persistence. 1-hour TTL by default.
Identical (model + system_prompt + user_message) → cached response.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

from src.personal_foundation.v2.state import StateStore

log = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 3600  # 1 hour


class LLMCache:
    """SQLite-backed LLM response cache with TTL."""

    def __init__(self, store: StateStore, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self.store = store
        self.ttl_seconds = ttl_seconds
        self._init_table()
        self._hits = 0
        self._misses = 0

    def _init_table(self) -> None:
        with self.store._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS llm_cache (
                    cache_key TEXT PRIMARY KEY,
                    model TEXT NOT NULL,
                    response TEXT NOT NULL,
                    tokens_used INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_expires ON llm_cache(expires_at)")

    def get(self, model: str, system_prompt: str, user_message: str) -> str | None:
        """Look up a cached response. Returns None on miss."""
        key = self._make_key(model, system_prompt, user_message)
        now = datetime.now(timezone.utc).isoformat()

        with self.store._conn() as conn:
            row = conn.execute(
                "SELECT response FROM llm_cache WHERE cache_key = ? AND expires_at > ?",
                (key, now),
            ).fetchone()

        if row:
            self._hits += 1
            log.debug("LLMCache: HIT (key=%s...)", key[:12])
            return row["response"]

        self._misses += 1
        return None

    def put(self, model: str, system_prompt: str, user_message: str, response: str, tokens_used: int = 0) -> None:
        """Store a response in the cache."""
        key = self._make_key(model, system_prompt, user_message)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=self.ttl_seconds)

        with self.store._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO llm_cache (cache_key, model, response, tokens_used, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (key, model, response, tokens_used, now.isoformat(), expires.isoformat()),
            )

    def invalidate(self, model: str = "", older_than_hours: int = 0) -> int:
        """Remove expired entries or all entries for a model. Returns count removed."""
        with self.store._conn() as conn:
            if older_than_hours:
                cutoff = (datetime.now(timezone.utc) - timedelta(hours=older_than_hours)).isoformat()
                cursor = conn.execute("DELETE FROM llm_cache WHERE created_at < ?", (cutoff,))
            elif model:
                cursor = conn.execute("DELETE FROM llm_cache WHERE model = ?", (model,))
            else:
                now = datetime.now(timezone.utc).isoformat()
                cursor = conn.execute("DELETE FROM llm_cache WHERE expires_at < ?", (now,))
            return cursor.rowcount

    @property
    def stats(self) -> dict:
        """Return cache hit/miss statistics."""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0
        with self.store._conn() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM llm_cache WHERE expires_at > ?",
                              (datetime.now(timezone.utc).isoformat(),)).fetchone()
            active_entries = row["cnt"] if row else 0
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 3),
            "active_entries": active_entries,
        }

    def _make_key(self, model: str, system_prompt: str, user_message: str) -> str:
        """Generate a deterministic cache key from inputs."""
        content = f"{model}|{system_prompt}|{user_message}"
        return hashlib.sha256(content.encode()).hexdigest()
