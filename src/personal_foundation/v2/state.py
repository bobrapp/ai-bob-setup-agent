"""SQLite state store for the v2 automation system.

Handles: audit log, approval queue, events, contacts, agent state, config.
All data persists across restarts. Append-only audit log.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DB_PATH = REPO_ROOT / "data" / "foundation.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    operator TEXT NOT NULL DEFAULT 'system',
    agent TEXT NOT NULL,
    action TEXT NOT NULL,
    model TEXT,
    prompt_summary TEXT,
    result_summary TEXT,
    status TEXT NOT NULL DEFAULT 'success',
    dry_run INTEGER NOT NULL DEFAULT 0,
    policy_result TEXT,
    git_sha TEXT,
    details_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_log(agent);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_status ON audit_log(status);

CREATE TABLE IF NOT EXISTS approval_queue (
    id TEXT PRIMARY KEY,
    agent TEXT NOT NULL,
    action_type TEXT NOT NULL,
    description TEXT NOT NULL,
    draft_content TEXT NOT NULL,
    rationale TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    reviewer TEXT,
    reviewed_at TEXT,
    rejection_reason TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_queue_status ON approval_queue(status);
CREATE INDEX IF NOT EXISTS idx_queue_created ON approval_queue(created_at);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    processed INTEGER NOT NULL DEFAULT 0,
    processed_by TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    processed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_type_processed ON events(event_type, processed);

CREATE TABLE IF NOT EXISTS outreach_contacts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT,
    pipeline_stage TEXT NOT NULL DEFAULT 'new',
    asana_task_id TEXT,
    last_contact_at TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_contacts_stage ON outreach_contacts(pipeline_stage);

CREATE TABLE IF NOT EXISTS agent_state (
    agent TEXT PRIMARY KEY,
    state_json TEXT NOT NULL DEFAULT '{}',
    suspended INTEGER NOT NULL DEFAULT 0,
    suspended_reason TEXT,
    suspended_at TEXT,
    last_run_at TEXT,
    failure_count_24h INTEGER NOT NULL DEFAULT 0,
    total_actions INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_by TEXT NOT NULL DEFAULT 'system'
);
"""


class StateStore:
    """SQLite-backed state store. Thread-safe via connection-per-call."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Audit Log (append-only)
    # ------------------------------------------------------------------

    def log_audit(
        self,
        agent: str,
        action: str,
        status: str = "success",
        operator: str = "system",
        model: str = "",
        prompt_summary: str = "",
        result_summary: str = "",
        dry_run: bool = False,
        policy_result: str = "",
        git_sha: str = "",
        details: dict | None = None,
    ) -> int:
        """Append an audit entry. Returns the sequence number."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO audit_log 
                   (timestamp, operator, agent, action, model, prompt_summary, 
                    result_summary, status, dry_run, policy_result, git_sha, details_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    now, operator, agent, action, model,
                    prompt_summary[:200] if prompt_summary else "",
                    result_summary[:200] if result_summary else "",
                    status, int(dry_run), policy_result, git_sha,
                    json.dumps(details or {}),
                ),
            )
            return cursor.lastrowid or 0

    def get_audit_log(
        self, limit: int = 100, agent: str = "", status: str = "", date: str = ""
    ) -> list[dict]:
        """Read audit log entries with optional filters."""
        query = "SELECT * FROM audit_log WHERE 1=1"
        params: list[Any] = []
        if agent:
            query += " AND agent LIKE ?"
            params.append(f"%{agent}%")
        if status:
            query += " AND status = ?"
            params.append(status)
        if date:
            query += " AND timestamp LIKE ?"
            params.append(f"{date}%")
        query += " ORDER BY seq DESC LIMIT ?"
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Approval Queue
    # ------------------------------------------------------------------

    def enqueue_approval(
        self,
        agent: str,
        action_type: str,
        description: str,
        draft_content: str,
        rationale: str = "",
    ) -> str:
        """Create an approval queue item. Returns the item ID."""
        item_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        expires = now.replace(hour=(now.hour + 24) % 24)  # +24h simplified
        from datetime import timedelta
        expires_at = (now + timedelta(hours=24)).isoformat()

        with self._conn() as conn:
            conn.execute(
                """INSERT INTO approval_queue 
                   (id, agent, action_type, description, draft_content, rationale, 
                    status, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (item_id, agent, action_type, description, draft_content,
                 rationale, now.isoformat(), expires_at),
            )
        return item_id

    def get_pending_approvals(self) -> list[dict]:
        """Get all pending/edited approval items, oldest first."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM approval_queue WHERE status IN ('pending', 'edited') ORDER BY created_at",
            ).fetchall()
            return [dict(r) for r in rows]

    def approve_item(self, item_id: str, reviewer: str) -> dict:
        """Approve an item. Returns the updated item."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE approval_queue SET status='approved', reviewer=?, reviewed_at=? WHERE id=?",
                (reviewer, now, item_id),
            )
            row = conn.execute("SELECT * FROM approval_queue WHERE id=?", (item_id,)).fetchone()
            return dict(row) if row else {}

    def reject_item(self, item_id: str, reviewer: str, reason: str = "") -> dict:
        """Reject an item. Returns the updated item."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE approval_queue SET status='rejected', reviewer=?, reviewed_at=?, rejection_reason=? WHERE id=?",
                (reviewer, now, reason, item_id),
            )
            row = conn.execute("SELECT * FROM approval_queue WHERE id=?", (item_id,)).fetchone()
            return dict(row) if row else {}

    def edit_item(self, item_id: str, new_content: str) -> dict:
        """Edit an item's draft content. Returns the updated item."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE approval_queue SET status='edited', draft_content=? WHERE id=?",
                (new_content, item_id),
            )
            row = conn.execute("SELECT * FROM approval_queue WHERE id=?", (item_id,)).fetchone()
            return dict(row) if row else {}

    # ------------------------------------------------------------------
    # Event Bus
    # ------------------------------------------------------------------

    def emit_event(self, event_type: str, payload: dict) -> int:
        """Emit an event. Returns the event ID."""
        with self._conn() as conn:
            cursor = conn.execute(
                "INSERT INTO events (event_type, payload_json) VALUES (?, ?)",
                (event_type, json.dumps(payload)),
            )
            return cursor.lastrowid or 0

    def get_unprocessed_events(self, event_type: str = "") -> list[dict]:
        """Get unprocessed events, optionally filtered by type pattern."""
        query = "SELECT * FROM events WHERE processed = 0"
        params: list[Any] = []
        if event_type:
            query += " AND event_type LIKE ?"
            params.append(event_type.replace("*", "%"))
        query += " ORDER BY id"
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def mark_event_processed(self, event_id: int, processed_by: str) -> None:
        """Mark an event as processed."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE events SET processed=1, processed_by=?, processed_at=? WHERE id=?",
                (processed_by, now, event_id),
            )

    # ------------------------------------------------------------------
    # Agent State
    # ------------------------------------------------------------------

    def get_agent_state(self, agent: str) -> dict:
        """Get agent state. Creates default if not exists."""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM agent_state WHERE agent=?", (agent,)).fetchone()
            if row:
                return dict(row)
            conn.execute(
                "INSERT INTO agent_state (agent, state_json) VALUES (?, '{}')",
                (agent,),
            )
            return {"agent": agent, "state_json": "{}", "suspended": 0,
                    "failure_count_24h": 0, "total_actions": 0}

    def suspend_agent(self, agent: str, reason: str = "") -> None:
        """Suspend an agent."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO agent_state (agent, suspended, suspended_reason, suspended_at, state_json)
                   VALUES (?, 1, ?, ?, '{}')
                   ON CONFLICT(agent) DO UPDATE SET suspended=1, suspended_reason=?, suspended_at=?""",
                (agent, reason, now, reason, now),
            )

    def resume_agent(self, agent: str) -> None:
        """Resume a suspended agent."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE agent_state SET suspended=0, suspended_reason=NULL, suspended_at=NULL WHERE agent=?",
                (agent,),
            )

    def is_agent_suspended(self, agent: str) -> bool:
        """Check if an agent is suspended."""
        state = self.get_agent_state(agent)
        return bool(state.get("suspended"))

    def increment_agent_actions(self, agent: str, success: bool = True) -> None:
        """Increment action count. Track failures for auto-suspension."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            if success:
                conn.execute(
                    """UPDATE agent_state SET total_actions = total_actions + 1, last_run_at = ?
                       WHERE agent = ?""",
                    (now, agent),
                )
            else:
                conn.execute(
                    """UPDATE agent_state SET total_actions = total_actions + 1, 
                       failure_count_24h = failure_count_24h + 1, last_run_at = ?
                       WHERE agent = ?""",
                    (now, agent),
                )
