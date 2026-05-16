"""Undo system — 5-second window to reverse an approval.

After Bob taps "Approve", the action is held for 5 seconds before execution.
During that window, Bob can tap "Undo" to cancel.

Implementation:
- On approve: set status to "approved_pending" (not yet executed)
- Start 5s timer
- If undo received within 5s: revert to "pending"
- If no undo: execute the action (set to "approved")
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Awaitable, Optional

from src.personal_foundation.v2.state import StateStore

log = logging.getLogger(__name__)

UNDO_WINDOW_SECONDS = 5


class UndoManager:
    """Manages the undo window for approval actions."""

    def __init__(self, store: StateStore) -> None:
        self.store = store
        self._pending_executions: dict[str, asyncio.Task] = {}
        self._undo_count = 0

    async def approve_with_undo(
        self,
        item_id: str,
        reviewer: str,
        execute_fn: Optional[Callable[[], Awaitable[None]]] = None,
        on_undo: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> dict:
        """Approve an item with a 5-second undo window.

        Args:
            item_id: The approval queue item ID
            reviewer: Who approved (bob/ken)
            execute_fn: Async function to call after undo window expires
            on_undo: Async function to call if undo is triggered

        Returns:
            The approval result dict (status may be "approved_pending" initially)
        """
        # Mark as approved (pending execution)
        result = self.store.approve_item(item_id, reviewer)

        # Start the delayed execution
        task = asyncio.create_task(
            self._delayed_execute(item_id, execute_fn)
        )
        self._pending_executions[item_id] = task

        log.info("UndoManager: approved %s (undo window: %ds)", item_id[:8], UNDO_WINDOW_SECONDS)
        return result

    async def undo(self, item_id: str) -> bool:
        """Undo an approval within the window. Returns True if successful."""
        task = self._pending_executions.get(item_id)
        if task and not task.done():
            task.cancel()
            del self._pending_executions[item_id]

            # Revert to pending
            with self.store._conn() as conn:
                conn.execute(
                    "UPDATE approval_queue SET status='pending', reviewer=NULL, reviewed_at=NULL WHERE id=?",
                    (item_id,),
                )

            self._undo_count += 1
            self.store.log_audit(
                agent="system/undo", action="undo_approval",
                result_summary=f"Approval undone for {item_id[:8]}",
            )
            log.info("UndoManager: undone %s", item_id[:8])
            return True

        log.warning("UndoManager: undo window expired for %s", item_id[:8])
        return False

    async def _delayed_execute(self, item_id: str, execute_fn: Optional[Callable] = None) -> None:
        """Wait for undo window, then execute."""
        try:
            await asyncio.sleep(UNDO_WINDOW_SECONDS)
            # Window expired — execute
            if execute_fn:
                await execute_fn()
            # Clean up
            self._pending_executions.pop(item_id, None)
            log.debug("UndoManager: executed %s (no undo received)", item_id[:8])
        except asyncio.CancelledError:
            # Undo was triggered
            pass

    @property
    def stats(self) -> dict:
        return {
            "pending_executions": len(self._pending_executions),
            "total_undos": self._undo_count,
            "undo_window_seconds": UNDO_WINDOW_SECONDS,
        }
