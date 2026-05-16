"""Agent memory — per-contact context for smarter drafts.

When drafting a reply to someone Bob has emailed before, includes the last 3
interactions as context. Makes replies contextually aware.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from src.personal_foundation.v2.state import StateStore

log = logging.getLogger(__name__)


class AgentMemory:
    """Per-contact memory for contextual agent responses."""

    def __init__(self, store: StateStore) -> None:
        self.store = store
        self._init_table()

    def _init_table(self) -> None:
        with self.store._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS contact_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    contact_key TEXT NOT NULL,
                    interaction_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_contact ON contact_memory(contact_key)")

    def record_interaction(self, contact_key: str, interaction_type: str, summary: str) -> None:
        """Record an interaction with a contact."""
        with self.store._conn() as conn:
            conn.execute(
                "INSERT INTO contact_memory (contact_key, interaction_type, summary, created_at) VALUES (?, ?, ?, ?)",
                (contact_key.lower(), interaction_type, summary[:500], datetime.now(timezone.utc).isoformat()),
            )

    def get_context(self, contact_key: str, limit: int = 3) -> str:
        """Get context string from prior interactions with a contact.

        Returns a string to append to the LLM prompt, or "" if no history.
        """
        with self.store._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM contact_memory WHERE contact_key = ? ORDER BY id DESC LIMIT ?",
                (contact_key.lower(), limit),
            ).fetchall()

        if not rows:
            return ""

        lines = ["\n--- PRIOR INTERACTIONS WITH THIS CONTACT ---"]
        for r in reversed(rows):
            lines.append(f"• [{r['interaction_type']}] {r['summary']}")
        lines.append("Use this context to write a more informed, personalized response.")
        return "\n".join(lines)

    def get_all_contacts(self) -> list[dict]:
        """List all contacts with interaction counts."""
        with self.store._conn() as conn:
            rows = conn.execute(
                "SELECT contact_key, COUNT(*) as count, MAX(created_at) as last_interaction FROM contact_memory GROUP BY contact_key ORDER BY last_interaction DESC"
            ).fetchall()
        return [dict(r) for r in rows]
