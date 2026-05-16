"""PostgreSQL state store — production replacement for SQLite.

Uses asyncpg for async Postgres access. Same interface as StateStore
but backed by Neon serverless Postgres.

Connection string from env: DATABASE_URL
Fallback: SQLite (for local dev)
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

log = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")

# Schema (Postgres version)
PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    seq SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    operator TEXT NOT NULL DEFAULT 'system',
    agent TEXT NOT NULL,
    action TEXT NOT NULL,
    model TEXT,
    prompt_summary TEXT,
    result_summary TEXT,
    status TEXT NOT NULL DEFAULT 'success',
    dry_run BOOLEAN NOT NULL DEFAULT FALSE,
    policy_result TEXT,
    git_sha TEXT,
    details_json JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_log(agent);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_status ON audit_log(status);

CREATE TABLE IF NOT EXISTS approval_queue (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL DEFAULT 'default',
    agent TEXT NOT NULL,
    action_type TEXT NOT NULL,
    description TEXT NOT NULL,
    draft_content TEXT NOT NULL,
    rationale TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    reviewer TEXT,
    reviewed_at TIMESTAMPTZ,
    rejection_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '24 hours')
);

CREATE INDEX IF NOT EXISTS idx_queue_status ON approval_queue(status);
CREATE INDEX IF NOT EXISTS idx_queue_org ON approval_queue(org_id);

CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    org_id TEXT NOT NULL DEFAULT 'default',
    event_type TEXT NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}',
    processed BOOLEAN NOT NULL DEFAULT FALSE,
    processed_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type, processed);
CREATE INDEX IF NOT EXISTS idx_events_org ON events(org_id);

CREATE TABLE IF NOT EXISTS organizations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    plan TEXT NOT NULL DEFAULT 'free',
    owner_email TEXT NOT NULL,
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    settings JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS org_users (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organizations(id),
    email TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'operator',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_users_org ON org_users(org_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON org_users(email);

CREATE TABLE IF NOT EXISTS agent_state (
    agent TEXT NOT NULL,
    org_id TEXT NOT NULL DEFAULT 'default',
    state_json JSONB NOT NULL DEFAULT '{}',
    suspended BOOLEAN NOT NULL DEFAULT FALSE,
    suspended_reason TEXT,
    suspended_at TIMESTAMPTZ,
    last_run_at TIMESTAMPTZ,
    failure_count_24h INTEGER NOT NULL DEFAULT 0,
    total_actions INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (agent, org_id)
);

-- Row-level security (tenant isolation)
ALTER TABLE approval_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE events ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_state ENABLE ROW LEVEL SECURITY;

-- Policies: each org can only see its own data
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'queue_org_isolation') THEN
        CREATE POLICY queue_org_isolation ON approval_queue
            USING (org_id = current_setting('app.current_org_id', TRUE));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'events_org_isolation') THEN
        CREATE POLICY events_org_isolation ON events
            USING (org_id = current_setting('app.current_org_id', TRUE));
    END IF;
END $$;
"""


class PostgresStore:
    """Async PostgreSQL state store with tenant isolation.

    Drop-in replacement for SQLite StateStore in production.
    Uses connection pooling via asyncpg.
    """

    def __init__(self, database_url: str = "") -> None:
        self.database_url = database_url or DATABASE_URL
        self._pool = None

    async def connect(self) -> None:
        """Initialize connection pool and create schema."""
        try:
            import asyncpg
            self._pool = await asyncpg.create_pool(
                self.database_url,
                min_size=2,
                max_size=10,
                command_timeout=30,
            )
            async with self._pool.acquire() as conn:
                await conn.execute(PG_SCHEMA)
            log.info("PostgresStore: connected to %s", self.database_url[:30] + "...")
        except ImportError:
            log.error("PostgresStore: asyncpg not installed. pip install asyncpg")
            raise
        except Exception as exc:
            log.error("PostgresStore: connection failed: %s", exc)
            raise

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()

    # ------------------------------------------------------------------
    # Audit Log
    # ------------------------------------------------------------------

    async def log_audit(self, agent: str, action: str, org_id: str = "default", **kwargs) -> int:
        """Append an audit entry. Returns sequence number."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO audit_log (agent, action, operator, model, prompt_summary, 
                   result_summary, status, dry_run, policy_result, git_sha, details_json)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                   RETURNING seq""",
                agent, action,
                kwargs.get("operator", "system"),
                kwargs.get("model", ""),
                (kwargs.get("prompt_summary", "") or "")[:200],
                (kwargs.get("result_summary", "") or "")[:200],
                kwargs.get("status", "success"),
                kwargs.get("dry_run", False),
                kwargs.get("policy_result", ""),
                kwargs.get("git_sha", ""),
                json.dumps(kwargs.get("details", {})),
            )
            return row["seq"]

    async def get_audit_log(self, limit: int = 100, org_id: str = "", **filters) -> list[dict]:
        """Read audit log entries."""
        query = "SELECT * FROM audit_log WHERE 1=1"
        params = []
        idx = 1

        if filters.get("agent"):
            query += f" AND agent LIKE ${idx}"
            params.append(f"%{filters['agent']}%")
            idx += 1
        if filters.get("status"):
            query += f" AND status = ${idx}"
            params.append(filters["status"])
            idx += 1

        query += f" ORDER BY seq DESC LIMIT ${idx}"
        params.append(limit)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Approval Queue
    # ------------------------------------------------------------------

    async def enqueue_approval(self, agent: str, action_type: str, description: str,
                               draft_content: str, org_id: str = "default", rationale: str = "") -> str:
        """Create an approval queue item."""
        item_id = str(uuid.uuid4())
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO approval_queue (id, org_id, agent, action_type, description, draft_content, rationale)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                item_id, org_id, agent, action_type, description, draft_content, rationale,
            )
        return item_id

    async def get_pending_approvals(self, org_id: str = "default") -> list[dict]:
        """Get pending items for an org."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM approval_queue WHERE org_id = $1 AND status IN ('pending', 'edited') ORDER BY created_at",
                org_id,
            )
            return [dict(r) for r in rows]

    async def approve_item(self, item_id: str, reviewer: str) -> dict:
        """Approve an item."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE approval_queue SET status='approved', reviewer=$1, reviewed_at=NOW() WHERE id=$2",
                reviewer, item_id,
            )
            row = await conn.fetchrow("SELECT * FROM approval_queue WHERE id=$1", item_id)
            return dict(row) if row else {}

    async def reject_item(self, item_id: str, reviewer: str, reason: str = "") -> dict:
        """Reject an item."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE approval_queue SET status='rejected', reviewer=$1, reviewed_at=NOW(), rejection_reason=$2 WHERE id=$3",
                reviewer, reason, item_id,
            )
            row = await conn.fetchrow("SELECT * FROM approval_queue WHERE id=$1", item_id)
            return dict(row) if row else {}

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def emit_event(self, event_type: str, payload: dict, org_id: str = "default") -> int:
        """Emit an event."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO events (org_id, event_type, payload_json) VALUES ($1, $2, $3) RETURNING id",
                org_id, event_type, json.dumps(payload),
            )
            return row["id"]

    async def get_unprocessed_events(self, pattern: str = "", org_id: str = "default") -> list[dict]:
        """Get unprocessed events."""
        query = "SELECT * FROM events WHERE processed = FALSE AND org_id = $1"
        params = [org_id]
        if pattern:
            query += " AND event_type LIKE $2"
            params.append(pattern.replace("*", "%"))
        query += " ORDER BY id"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [dict(r) for r in rows]

    async def mark_event_processed(self, event_id: int, processed_by: str) -> None:
        """Mark an event as processed."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE events SET processed=TRUE, processed_by=$1, processed_at=NOW() WHERE id=$2",
                processed_by, event_id,
            )

    # ------------------------------------------------------------------
    # Organizations
    # ------------------------------------------------------------------

    async def create_org(self, name: str, slug: str, owner_email: str, plan: str = "free") -> str:
        """Create a new organization."""
        org_id = str(uuid.uuid4())
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO organizations (id, name, slug, owner_email, plan) VALUES ($1, $2, $3, $4, $5)",
                org_id, name, slug, owner_email, plan,
            )
        return org_id

    async def get_org(self, org_id: str) -> dict | None:
        """Get an organization by ID."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM organizations WHERE id=$1", org_id)
            return dict(row) if row else None

    async def get_org_by_slug(self, slug: str) -> dict | None:
        """Get an organization by slug."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM organizations WHERE slug=$1", slug)
            return dict(row) if row else None
