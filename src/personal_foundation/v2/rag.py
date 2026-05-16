"""RAG (Retrieval-Augmented Generation) for research deduplication and context.

Uses SQLite FTS5 (full-text search) to index prior research items.
Before scoring a new item, checks if it's already been seen (by URL or title similarity).
Also provides context from prior items to improve scoring accuracy.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from src.personal_foundation.v2.state import StateStore

log = logging.getLogger(__name__)


class ResearchRAG:
    """SQLite FTS5-backed research item index for deduplication and context."""

    def __init__(self, store: StateStore) -> None:
        self.store = store
        self._init_tables()

    def _init_tables(self) -> None:
        with self.store._conn() as conn:
            # Main research items table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS research_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url_hash TEXT UNIQUE NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT,
                    relevance_score INTEGER DEFAULT 0,
                    pillar_scores_json TEXT,
                    scan_date TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            # FTS5 index for full-text search
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS research_fts USING fts5(
                    title, summary, url,
                    content=research_items,
                    content_rowid=id
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_research_url ON research_items(url_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_research_score ON research_items(relevance_score)")

    def is_duplicate(self, url: str) -> bool:
        """Check if a URL has already been indexed."""
        url_hash = self._hash_url(url)
        with self.store._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM research_items WHERE url_hash = ?", (url_hash,)
            ).fetchone()
        return row is not None

    def index_item(self, url: str, title: str, summary: str = "", relevance_score: int = 0, pillar_scores: dict = None) -> int:
        """Index a research item. Returns the item ID. Skips duplicates."""
        url_hash = self._hash_url(url)

        if self.is_duplicate(url):
            log.debug("ResearchRAG: duplicate skipped: %s", url[:60])
            return 0

        import json
        with self.store._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO research_items (url_hash, url, title, summary, relevance_score, pillar_scores_json, scan_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (url_hash, url, title, summary or "", relevance_score,
                 json.dumps(pillar_scores or {}),
                 datetime.now(timezone.utc).strftime("%Y-%m-%d")),
            )
            item_id = cursor.lastrowid

            # Update FTS index
            conn.execute(
                "INSERT INTO research_fts (rowid, title, summary, url) VALUES (?, ?, ?, ?)",
                (item_id, title, summary or "", url),
            )

        log.debug("ResearchRAG: indexed item %d: %s", item_id, title[:50])
        return item_id or 0

    def search_similar(self, query: str, limit: int = 5) -> list[dict]:
        """Search for similar items using FTS5. Returns matching items."""
        with self.store._conn() as conn:
            rows = conn.execute(
                """SELECT r.*, rank FROM research_fts f
                   JOIN research_items r ON f.rowid = r.id
                   WHERE research_fts MATCH ?
                   ORDER BY rank LIMIT ?""",
                (query, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_context_for_scoring(self, title: str, limit: int = 3) -> str:
        """Get context from similar prior items to improve scoring.

        Returns a string that can be appended to the LLM prompt.
        """
        similar = self.search_similar(title, limit=limit)
        if not similar:
            return ""

        lines = ["\n--- PRIOR SIMILAR ITEMS (for context) ---"]
        for item in similar:
            score = item.get("relevance_score", 0)
            lines.append(f"- [{score}/5] {item['title']}")
            if item.get("summary"):
                lines.append(f"  Summary: {item['summary'][:100]}...")
        lines.append("Use these as calibration for your scoring.")
        return "\n".join(lines)

    def get_stats(self) -> dict:
        """Get index statistics."""
        with self.store._conn() as conn:
            total = conn.execute("SELECT COUNT(*) as cnt FROM research_items").fetchone()["cnt"]
            high_rel = conn.execute(
                "SELECT COUNT(*) as cnt FROM research_items WHERE relevance_score >= 4"
            ).fetchone()["cnt"]
            recent = conn.execute(
                "SELECT COUNT(*) as cnt FROM research_items WHERE scan_date = ?",
                (datetime.now(timezone.utc).strftime("%Y-%m-%d"),),
            ).fetchone()["cnt"]

        return {
            "total_indexed": total,
            "high_relevance": high_rel,
            "indexed_today": recent,
        }

    def _hash_url(self, url: str) -> str:
        """Generate a deterministic hash for a URL."""
        normalized = url.strip().lower().rstrip("/")
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]
