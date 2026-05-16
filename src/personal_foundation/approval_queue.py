"""Approval Queue for the personal + foundation automation system.

INTERNAL USE ONLY — not part of the ai-bob-setup-agent customer product.

Every consequential agent action passes through this queue before execution.
Bob or Ken approve, reject, or edit items via Telegram (Requirement 12).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional


@dataclass
class ApprovalItem:
    """A single item pending human review in the Approval_Queue.

    Fields match the design doc exactly. item_id is auto-generated if not provided.
    """

    agent: str              # prefixed agent name, e.g. "personal/email_agent"
    action_type: str        # "email_draft" | "calendar_confirm" | "post" | ...
    description: str        # plain-language description shown to Bob/Ken
    draft_content: str      # the actual draft or decision text
    rationale: str = ""     # one-line editorial rationale (Writing_Agent)
    item_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(default=None)  # type: ignore[assignment]
    status: str = "pending"  # "pending" | "approved" | "rejected" | "edited"
    reviewer: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None

    def __post_init__(self) -> None:
        if self.expires_at is None:
            self.expires_at = self.created_at + timedelta(hours=24)


class ApprovalQueue:
    """In-memory Approval_Queue with full state machine.

    Items are stored in a dict keyed by item_id. The queue is intentionally
    in-memory for simplicity; the Audit_Logger provides the durable record.
    """

    def __init__(self) -> None:
        self._items: dict[str, ApprovalItem] = {}

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def enqueue(self, item: ApprovalItem) -> None:
        """Add an item to the queue. Raises ValueError if item_id already exists."""
        if item.item_id in self._items:
            raise ValueError(f"ApprovalItem '{item.item_id}' already in queue.")
        self._items[item.item_id] = item

    def approve(self, item_id: str, reviewer: str) -> ApprovalItem:
        """Mark an item as approved. Returns the updated item.

        Raises:
            KeyError: If item_id not found.
            ValueError: If item is not in 'pending' or 'edited' status.
        """
        item = self._get(item_id)
        if item.status not in ("pending", "edited"):
            raise ValueError(
                f"Cannot approve item '{item_id}' with status '{item.status}'."
            )
        item.status = "approved"
        item.reviewer = reviewer
        item.reviewed_at = datetime.now(timezone.utc)
        return item

    def reject(self, item_id: str, reviewer: str, reason: str = "") -> ApprovalItem:
        """Mark an item as rejected. Returns the updated item.

        Raises:
            KeyError: If item_id not found.
            ValueError: If item is not in 'pending' or 'edited' status.
        """
        item = self._get(item_id)
        if item.status not in ("pending", "edited"):
            raise ValueError(
                f"Cannot reject item '{item_id}' with status '{item.status}'."
            )
        item.status = "rejected"
        item.reviewer = reviewer
        item.reviewed_at = datetime.now(timezone.utc)
        item.rejection_reason = reason
        return item

    def edit(self, item_id: str, new_content: str) -> ApprovalItem:
        """Replace the draft content and set status to 'edited' for re-review.

        Raises:
            KeyError: If item_id not found.
            ValueError: If item is not in 'pending' status.
        """
        item = self._get(item_id)
        if item.status != "pending":
            raise ValueError(
                f"Cannot edit item '{item_id}' with status '{item.status}'. "
                "Only 'pending' items can be edited."
            )
        item.draft_content = new_content
        item.status = "edited"
        return item

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def pending(self) -> list[ApprovalItem]:
        """Return all items with status 'pending' or 'edited', oldest first."""
        return sorted(
            [i for i in self._items.values() if i.status in ("pending", "edited")],
            key=lambda i: i.created_at,
        )

    def overdue(self, threshold_hours: int = 24) -> list[ApprovalItem]:
        """Return pending items that have exceeded the review threshold."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=threshold_hours)
        return [
            i for i in self.pending()
            if i.created_at <= cutoff
        ]

    def get(self, item_id: str) -> Optional[ApprovalItem]:
        """Return an item by ID, or None if not found."""
        return self._items.get(item_id)

    def all_items(self) -> list[ApprovalItem]:
        """Return all items regardless of status, oldest first."""
        return sorted(self._items.values(), key=lambda i: i.created_at)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get(self, item_id: str) -> ApprovalItem:
        item = self._items.get(item_id)
        if item is None:
            raise KeyError(f"ApprovalItem '{item_id}' not found in queue.")
        return item

    def __len__(self) -> int:
        return len(self.pending())
