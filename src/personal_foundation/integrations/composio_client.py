"""Composio API client for Asana and Trello integration.

INTERNAL USE ONLY — not part of the ai-bob-setup-agent customer product.

Wraps the Composio backend API for task management actions on Asana and Trello.
All methods respect dry_run mode — no HTTP calls are made when dry_run=True.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from src.personal_foundation.config import ComposioConfig

log = logging.getLogger(__name__)

COMPOSIO_API_BASE = "https://backend.composio.dev/api/v1"


class ComposioAPIError(Exception):
    """Raised when the Composio API returns an error."""


class ComposioClient:
    """Wraps Composio API for Asana and Trello operations.

    All methods check dry_run and log instead of calling the API when set.
    """

    def __init__(self, config: "ComposioConfig", dry_run: bool = False) -> None:
        self.config = config
        self.dry_run = dry_run
        self._client = httpx.Client(
            base_url=COMPOSIO_API_BASE,
            headers={
                "x-api-key": config.api_key,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    # ------------------------------------------------------------------
    # Asana operations
    # ------------------------------------------------------------------

    def create_asana_task(
        self,
        title: str,
        assignee_email: str,
        due_date: date | str | None = None,
        notes: str = "",
        meeting_ref: str = "",
    ) -> dict:
        """Create a task in the configured Asana workspace.

        Args:
            title: Task name.
            assignee_email: Email address of the assignee.
            due_date: Due date as a date object or ISO string (YYYY-MM-DD).
            notes: Task notes / description.
            meeting_ref: Optional reference to the originating meeting.

        Returns:
            Task dict with at minimum ``{"gid": str, "name": str}``.
            Returns empty dict on failure.
        """
        if self.dry_run:
            log.info(
                "[dry_run] composio_client.create_asana_task title=%r assignee=%s due=%s",
                title,
                assignee_email,
                due_date,
            )
            return {"gid": "dry_run_task_gid", "name": title}

        payload: dict[str, Any] = {
            "workspace": self.config.asana_workspace_id,
            "name": title,
            "assignee": assignee_email,
            "notes": notes,
        }
        if due_date:
            payload["due_on"] = (
                due_date.isoformat() if isinstance(due_date, date) else due_date
            )
        if meeting_ref:
            payload["external"] = {"data": meeting_ref}

        try:
            resp = self._client.post(
                "/actions/execute",
                json={
                    "action": "ASANA_CREATE_TASK",
                    "input": payload,
                },
            )
            self._raise_for_status(resp)
            data = resp.json()
            task = data.get("data", data)
            return {"gid": str(task.get("gid", "")), "name": task.get("name", title), **task}
        except httpx.HTTPError as exc:
            log.error("composio_client.create_asana_task failed: %s", exc)
            return {}

    def update_asana_task(self, task_gid: str, **fields: Any) -> dict:
        """Update fields on an existing Asana task.

        Args:
            task_gid: The Asana task GID.
            **fields: Arbitrary task fields to update (e.g. name, notes, due_on).

        Returns:
            Updated task dict, or empty dict on failure.
        """
        if self.dry_run:
            log.info(
                "[dry_run] composio_client.update_asana_task task_gid=%s fields=%s",
                task_gid,
                list(fields.keys()),
            )
            return {"gid": task_gid, **fields}

        try:
            resp = self._client.post(
                "/actions/execute",
                json={
                    "action": "ASANA_UPDATE_TASK",
                    "input": {"task_gid": task_gid, **fields},
                },
            )
            self._raise_for_status(resp)
            data = resp.json()
            return data.get("data", data)
        except httpx.HTTPError as exc:
            log.error(
                "composio_client.update_asana_task failed task_gid=%s: %s",
                task_gid,
                exc,
            )
            return {}

    def complete_asana_task(self, task_gid: str) -> bool:
        """Mark an Asana task as complete.

        Args:
            task_gid: The Asana task GID.

        Returns:
            True on success, False on failure.
        """
        if self.dry_run:
            log.info(
                "[dry_run] composio_client.complete_asana_task task_gid=%s", task_gid
            )
            return True

        try:
            resp = self._client.post(
                "/actions/execute",
                json={
                    "action": "ASANA_UPDATE_TASK",
                    "input": {"task_gid": task_gid, "completed": True},
                },
            )
            self._raise_for_status(resp)
            data = resp.json()
            task = data.get("data", data)
            return bool(task.get("completed", False))
        except httpx.HTTPError as exc:
            log.error(
                "composio_client.complete_asana_task failed task_gid=%s: %s",
                task_gid,
                exc,
            )
            return False

    def get_asana_task(self, task_gid: str) -> dict:
        """Fetch task data from Asana.

        Returns a dict including at minimum:
        ``last_modified_at``, ``completed``, ``assignee``, ``notes``.

        Args:
            task_gid: The Asana task GID.

        Returns:
            Task data dict, or empty dict on failure.
        """
        if self.dry_run:
            log.info(
                "[dry_run] composio_client.get_asana_task task_gid=%s", task_gid
            )
            return {
                "gid": task_gid,
                "name": "[dry-run task]",
                "completed": False,
                "assignee": None,
                "notes": "",
                "last_modified_at": None,
            }

        try:
            resp = self._client.post(
                "/actions/execute",
                json={
                    "action": "ASANA_GET_TASK",
                    "input": {"task_gid": task_gid},
                },
            )
            self._raise_for_status(resp)
            data = resp.json()
            return data.get("data", data)
        except httpx.HTTPError as exc:
            log.error(
                "composio_client.get_asana_task failed task_gid=%s: %s",
                task_gid,
                exc,
            )
            return {}

    def list_asana_tasks(
        self,
        workspace_id: str | None = None,
        assignee: str | None = None,
        modified_since: str | None = None,
    ) -> list[dict]:
        """List Asana tasks with optional filters.

        Args:
            workspace_id: Asana workspace GID. Defaults to configured workspace.
            assignee: Filter by assignee email or 'me'.
            modified_since: ISO 8601 datetime string to filter recently modified tasks.

        Returns:
            List of task dicts, or empty list on failure.
        """
        if self.dry_run:
            log.info(
                "[dry_run] composio_client.list_asana_tasks workspace_id=%s "
                "assignee=%s modified_since=%s",
                workspace_id,
                assignee,
                modified_since,
            )
            return []

        params: dict[str, Any] = {
            "workspace": workspace_id or self.config.asana_workspace_id,
        }
        if assignee:
            params["assignee"] = assignee
        if modified_since:
            params["modified_since"] = modified_since

        try:
            resp = self._client.post(
                "/actions/execute",
                json={
                    "action": "ASANA_LIST_TASKS",
                    "input": params,
                },
            )
            self._raise_for_status(resp)
            data = resp.json()
            tasks = data.get("data", data)
            if isinstance(tasks, list):
                return tasks
            return tasks.get("data", []) if isinstance(tasks, dict) else []
        except httpx.HTTPError as exc:
            log.error("composio_client.list_asana_tasks failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Trello operations
    # ------------------------------------------------------------------

    def update_trello_card(self, card_id: str, **fields: Any) -> bool:
        """Update a Trello card.

        Common usage: pass ``closed=True`` to mark a card as complete/archived.

        Args:
            card_id: The Trello card ID.
            **fields: Arbitrary card fields to update (e.g. closed, name, desc).

        Returns:
            True on success, False on failure.
        """
        if self.dry_run:
            log.info(
                "[dry_run] composio_client.update_trello_card card_id=%s fields=%s",
                card_id,
                list(fields.keys()),
            )
            return True

        try:
            resp = self._client.post(
                "/actions/execute",
                json={
                    "action": "TRELLO_UPDATE_CARD",
                    "input": {"card_id": card_id, **fields},
                },
            )
            self._raise_for_status(resp)
            return True
        except httpx.HTTPError as exc:
            log.error(
                "composio_client.update_trello_card failed card_id=%s: %s",
                card_id,
                exc,
            )
            return False

    def find_trello_card(self, name: str) -> dict | None:
        """Find a Trello card by name on the configured board.

        Args:
            name: The card name to search for (case-insensitive match).

        Returns:
            Card dict with at minimum ``{"id": str, "name": str}``,
            or None if not found.
        """
        if self.dry_run:
            log.info(
                "[dry_run] composio_client.find_trello_card name=%r", name
            )
            return None

        try:
            resp = self._client.post(
                "/actions/execute",
                json={
                    "action": "TRELLO_SEARCH_CARDS",
                    "input": {
                        "board_id": self.config.trello_board_id,
                        "query": name,
                    },
                },
            )
            self._raise_for_status(resp)
            data = resp.json()
            cards = data.get("data", data)
            if isinstance(cards, list) and cards:
                # Return the first matching card
                return cards[0]
            if isinstance(cards, dict):
                results = cards.get("cards", cards.get("data", []))
                if results:
                    return results[0]
            return None
        except httpx.HTTPError as exc:
            log.error(
                "composio_client.find_trello_card failed name=%r: %s", name, exc
            )
            return None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            raise ComposioAPIError(
                f"Composio API error {resp.status_code}: {resp.text[:200]}"
            )
