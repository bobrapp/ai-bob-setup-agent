"""Feedback loop — learns from Bob's edits to improve agent output over time.

When Bob edits a draft before approving, the (input, original_output, edited_output)
triple is stored. The engine injects the last N feedback examples as few-shot
context in future prompts for the same agent.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from src.personal_foundation.v2.state import StateStore

log = logging.getLogger(__name__)

MAX_FEEDBACK_EXAMPLES = 5  # Include last 5 edits as few-shot context


class FeedbackStore:
    """Stores and retrieves feedback examples for agent improvement."""

    def __init__(self, store: StateStore) -> None:
        self.store = store
        self._init_table()

    def _init_table(self) -> None:
        with self.store._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent TEXT NOT NULL,
                    input_summary TEXT NOT NULL,
                    original_output TEXT NOT NULL,
                    edited_output TEXT NOT NULL,
                    edit_type TEXT DEFAULT 'content',
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_agent ON feedback(agent)")

    def record_edit(self, agent: str, input_summary: str, original: str, edited: str, edit_type: str = "content") -> None:
        """Record a feedback example when Bob edits an agent's output."""
        with self.store._conn() as conn:
            conn.execute(
                """INSERT INTO feedback (agent, input_summary, original_output, edited_output, edit_type, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (agent, input_summary[:500], original[:2000], edited[:2000], edit_type,
                 datetime.now(timezone.utc).isoformat()),
            )
        log.info("Feedback: recorded edit for %s (type=%s)", agent, edit_type)

        self.store.log_audit(
            agent="system/feedback", action="record_edit",
            result_summary=f"Feedback recorded for {agent}: {edit_type}",
        )

    def get_examples(self, agent: str, limit: int = MAX_FEEDBACK_EXAMPLES) -> list[dict]:
        """Get the most recent feedback examples for an agent."""
        with self.store._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM feedback WHERE agent = ? ORDER BY id DESC LIMIT ?",
                (agent, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def build_few_shot_context(self, agent: str) -> str:
        """Build a few-shot context string from recent feedback.

        Returns a string to append to the system prompt, showing the agent
        how Bob prefers things to be written.
        """
        examples = self.get_examples(agent)
        if not examples:
            return ""

        lines = [
            "\n\n--- LEARNING FROM PAST FEEDBACK ---",
            "Here are recent examples of how the operator edited your output.",
            "Learn from these to better match their preferences:\n",
        ]

        for i, ex in enumerate(reversed(examples), 1):
            lines.append(f"Example {i}:")
            lines.append(f"  Input: {ex['input_summary'][:100]}")
            lines.append(f"  Your output: {ex['original_output'][:150]}...")
            lines.append(f"  Operator edited to: {ex['edited_output'][:150]}...")
            lines.append("")

        lines.append("Apply these patterns to your current task.")
        return "\n".join(lines)

    def get_stats(self, agent: str = "") -> dict:
        """Get feedback statistics."""
        with self.store._conn() as conn:
            if agent:
                row = conn.execute("SELECT COUNT(*) as cnt FROM feedback WHERE agent = ?", (agent,)).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) as cnt FROM feedback").fetchone()
            total = row["cnt"] if row else 0

            # Get per-agent breakdown
            rows = conn.execute(
                "SELECT agent, COUNT(*) as cnt FROM feedback GROUP BY agent ORDER BY cnt DESC"
            ).fetchall()
            by_agent = {r["agent"]: r["cnt"] for r in rows}

        return {"total_feedback": total, "by_agent": by_agent}
