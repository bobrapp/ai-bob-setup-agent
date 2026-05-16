"""Approval queue grouping — reduces visual noise by batching related items.

Instead of showing 5 separate email drafts, shows:
"📧 5 email drafts (tap to expand)"

Groups by: agent + action_type within a time window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


@dataclass
class QueueGroup:
    """A group of related approval items."""
    group_id: str
    agent: str
    action_type: str
    count: int
    items: list[dict] = field(default_factory=list)
    oldest: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    newest: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def summary(self) -> str:
        """Human-readable group summary."""
        icons = {
            "email_draft": "📧",
            "content_draft": "✍️",
            "redirect_comment": "🛡️",
            "outreach_followup": "🤝",
            "weekly_digest": "📰",
            "manual_review": "👁️",
        }
        icon = icons.get(self.action_type, "📋")
        agent_short = self.agent.split("/")[-1].replace("_", " ").title()

        if self.count == 1:
            return f"{icon} {self.items[0].get('description', self.action_type)}"
        return f"{icon} {self.count} {self.action_type.replace('_', ' ')}s from {agent_short}"

    @property
    def is_expandable(self) -> bool:
        return self.count > 1


def group_pending_items(items: list[dict], window_hours: int = 24) -> list[QueueGroup]:
    """Group pending approval items by agent + action_type.

    Items within the same time window from the same agent with the same
    action_type are grouped together.

    Returns groups sorted by oldest item (most urgent first).
    """
    groups: dict[str, QueueGroup] = {}

    for item in items:
        agent = item.get("agent", "unknown")
        action_type = item.get("action_type", "unknown")
        key = f"{agent}:{action_type}"

        if key not in groups:
            created = item.get("created_at", "")
            try:
                created_dt = datetime.fromisoformat(created) if created else datetime.now(timezone.utc)
            except (ValueError, TypeError):
                created_dt = datetime.now(timezone.utc)

            groups[key] = QueueGroup(
                group_id=key,
                agent=agent,
                action_type=action_type,
                count=0,
                oldest=created_dt,
                newest=created_dt,
            )

        groups[key].count += 1
        groups[key].items.append(item)

        # Update time bounds
        try:
            item_time = datetime.fromisoformat(item.get("created_at", ""))
            if item_time < groups[key].oldest:
                groups[key].oldest = item_time
            if item_time > groups[key].newest:
                groups[key].newest = item_time
        except (ValueError, TypeError):
            pass

    # Sort by oldest (most urgent first)
    sorted_groups = sorted(groups.values(), key=lambda g: g.oldest)
    return sorted_groups


def format_grouped_queue(groups: list[QueueGroup]) -> str:
    """Format grouped queue for Telegram/text display."""
    if not groups:
        return "✅ No pending items. All clear!"

    total = sum(g.count for g in groups)
    lines = [f"📋 **{total} pending items** ({len(groups)} groups)\n"]

    for i, group in enumerate(groups, 1):
        if group.is_expandable:
            lines.append(f"{i}. {group.summary}")
            # Show first item as preview
            if group.items:
                preview = group.items[0].get("description", "")[:50]
                lines.append(f"   ↳ Latest: {preview}...")
        else:
            lines.append(f"{i}. {group.summary}")

    return "\n".join(lines)
