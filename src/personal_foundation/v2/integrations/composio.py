"""Composio integration — Asana task creation and Trello sync."""

from __future__ import annotations

import logging
import os

import httpx

from src.personal_foundation.v2.state import StateStore

log = logging.getLogger(__name__)

COMPOSIO_API_URL = "https://backend.composio.dev/api/v1"


class ComposioIntegration:
    """Composio API for Asana + Trello operations."""

    def __init__(self, store: StateStore, dry_run: bool = False) -> None:
        self.store = store
        self.dry_run = dry_run
        self._api_key = os.getenv("COMPOSIO_API_KEY", "")
        self._client = httpx.AsyncClient(timeout=30)

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def create_asana_task(self, name: str, assignee: str = "", due_date: str = "", notes: str = "") -> dict:
        """Create a task in Asana via Composio."""
        if self.dry_run:
            log.info("[dry_run] Composio: would create Asana task '%s'", name)
            return {"id": "dry_run_task", "name": name}

        if not self.is_configured:
            log.warning("Composio: API key not configured")
            return {}

        try:
            resp = await self._client.post(
                f"{COMPOSIO_API_URL}/actions/asana_create_task/execute",
                headers={"X-API-Key": self._api_key},
                json={
                    "input": {
                        "name": name,
                        "assignee": assignee,
                        "due_on": due_date,
                        "notes": notes,
                        "workspace": os.getenv("ASANA_WORKSPACE_ID", ""),
                    }
                },
            )
            resp.raise_for_status()
            result = resp.json()
            self.store.log_audit(
                agent="personal/task_agent", action="create_asana_task",
                status="success", result_summary=f"Created: {name[:50]}",
            )
            return result
        except Exception as exc:
            log.error("Composio: create_asana_task failed: %s", exc)
            self.store.log_audit(
                agent="personal/task_agent", action="create_asana_task",
                status="failure", result_summary=f"Failed: {type(exc).__name__}",
            )
            return {}

    async def update_trello_card(self, card_id: str, updates: dict) -> bool:
        """Update a Trello card via Composio."""
        if self.dry_run:
            log.info("[dry_run] Composio: would update Trello card %s", card_id)
            return True

        if not self.is_configured:
            return False

        try:
            resp = await self._client.post(
                f"{COMPOSIO_API_URL}/actions/trello_update_card/execute",
                headers={"X-API-Key": self._api_key},
                json={"input": {"card_id": card_id, **updates}},
            )
            resp.raise_for_status()
            return True
        except Exception as exc:
            log.error("Composio: update_trello_card failed: %s", exc)
            return False

    async def get_stale_tasks(self, days: int = 7) -> list[dict]:
        """Get Asana tasks that haven't been updated in N days."""
        if self.dry_run or not self.is_configured:
            return []

        try:
            resp = await self._client.post(
                f"{COMPOSIO_API_URL}/actions/asana_get_tasks/execute",
                headers={"X-API-Key": self._api_key},
                json={
                    "input": {
                        "workspace": os.getenv("ASANA_WORKSPACE_ID", ""),
                        "modified_since_days_ago": days,
                        "completed": False,
                    }
                },
            )
            resp.raise_for_status()
            return resp.json().get("data", [])
        except Exception as exc:
            log.error("Composio: get_stale_tasks failed: %s", exc)
            return []
