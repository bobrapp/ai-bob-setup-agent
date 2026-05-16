"""Shared data models for the personal + foundation automation system.

INTERNAL USE ONLY — not part of the ai-bob-setup-agent customer product.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Outreach pipeline
# ---------------------------------------------------------------------------


class PipelineStage(str, Enum):
    """Stages in the outreach pipeline (Requirement 9)."""

    NEW = "new"
    FIRST_CONTACT_SENT = "first-contact-sent"
    RESPONDED_INTERESTED = "responded-interested"
    RESPONDED_NOT_INTERESTED = "responded-not-interested"
    NEEDS_MORE_INFO = "needs-more-info"
    PARTNER_CONFIRMED = "partner-confirmed"
    ARCHIVED = "archived"


@dataclass
class OutreachContact:
    """A contact in the outreach pipeline."""

    contact_id: str
    name: str
    pipeline_stage: PipelineStage
    asana_task_id: str
    last_contact_date: datetime | None = None
    notes: str = ""


# ---------------------------------------------------------------------------
# Research
# ---------------------------------------------------------------------------

FOUNDATION_PILLARS = (
    "governance_as_code",
    "ai_technical_debt",
    "operational_compliance",
    "community_driven_standards",
)


@dataclass
class ResearchItem:
    """A research item found during a daily scan (Requirement 3)."""

    item_id: str
    source_url: str
    title: str
    published_at: datetime
    pillar_scores: dict[str, int]  # {pillar_name: 1-5}
    relevance_score: int           # max of pillar_scores; 1–5
    scan_session_id: str
    summary: str | None = None     # ≤150 words; None if relevance_score < 4

    def to_json(self) -> str:
        """Serialize to a JSON string. Deterministic round-trip guaranteed."""
        data = {
            "item_id": self.item_id,
            "source_url": self.source_url,
            "title": self.title,
            "published_at": self.published_at.isoformat(),
            "pillar_scores": self.pillar_scores,
            "relevance_score": self.relevance_score,
            "scan_session_id": self.scan_session_id,
            "summary": self.summary,
        }
        return json.dumps(data, sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> "ResearchItem":
        """Deserialize from a JSON string. Inverse of to_json()."""
        data = json.loads(s)
        return cls(
            item_id=data["item_id"],
            source_url=data["source_url"],
            title=data["title"],
            published_at=datetime.fromisoformat(data["published_at"]),
            pillar_scores=data["pillar_scores"],
            relevance_score=data["relevance_score"],
            scan_session_id=data["scan_session_id"],
            summary=data.get("summary"),
        )


# ---------------------------------------------------------------------------
# Circle.so
# ---------------------------------------------------------------------------


@dataclass
class CirclePost:
    """A post or comment in the Circle.so community."""

    post_id: str
    space_id: str
    author_member_id: str
    title: str
    body: str
    published_at: datetime
    reactions: int = 0
    comments: int = 0
    tags: list[str] = field(default_factory=list)
    last_activity_at: datetime | None = None

    @property
    def engagement(self) -> int:
        """Combined reactions + comments (Requirement 7.1)."""
        return self.reactions + self.comments


@dataclass
class CircleMember:
    """A Circle.so community member."""

    member_id: str
    display_name: str
    bio: str = ""
    role: str = ""
    organization: str = ""
    ai_governance_interests: list[str] = field(default_factory=list)
    interest_tags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

EMAIL_CATEGORIES = frozenset(
    {"action-required", "FYI-only", "newsletter", "spam", "foundation-business"}
)


@dataclass
class EmailClassification:
    """Result of classifying an email (Requirement 1)."""

    category: str          # one of EMAIL_CATEGORIES, or "" if low-confidence
    confidence: float      # 0.0–1.0
    subject_line: str | None = None  # draft subject if action-required


@dataclass
class EmailMessage:
    """A simplified email message for agent processing."""

    message_id: str
    sender: str
    subject: str
    body_preview: str      # first 500 chars; never store full body in audit log
    received_at: datetime
    is_outreach_contact: bool = False
    outreach_contact_id: str | None = None


# ---------------------------------------------------------------------------
# Calendar / meetings
# ---------------------------------------------------------------------------


@dataclass
class MeetingBriefing:
    """Pre-meeting briefing document (Requirement 2.3)."""

    meeting_id: str
    attendee_backgrounds: list[dict[str, str]]  # [{name, background}]
    recent_notes: list[dict[str, Any]]          # last 5 Granola notes with overlap
    suggested_agenda: list[str]                 # agenda items


@dataclass
class MeetingNotes:
    """Notes retrieved from Granola for a completed meeting."""

    meeting_id: str
    title: str
    date: datetime
    attendees: list[str]
    summary: str
    action_items: list[dict[str, str]]  # [{description, assignee, due_date}]
    transcript: str | None = None


# ---------------------------------------------------------------------------
# Governance reporting
# ---------------------------------------------------------------------------


@dataclass
class WeeklyGovernanceReport:
    """Weekly governance report (Requirement 10.4)."""

    period_start: date
    period_end: date
    total_actions: int
    actions_by_agent: dict[str, int]
    approval_queue_throughput: int      # items approved + rejected
    overall_failure_rate: float
    agent_failure_rates: dict[str, float]
    anomalies: list[str]                # agents above threshold
    consecutive_failure_agents: list[str]

    def to_markdown(self) -> str:
        """Format as a readable Markdown report."""
        lines = [
            f"# Weekly Governance Report",
            f"**Period:** {self.period_start} → {self.period_end}",
            f"",
            f"## Summary",
            f"- Total actions: {self.total_actions}",
            f"- Approval queue throughput: {self.approval_queue_throughput}",
            f"- Overall failure rate: {self.overall_failure_rate:.1%}",
            f"",
            f"## Actions by Agent",
        ]
        for agent, count in sorted(self.actions_by_agent.items()):
            rate = self.agent_failure_rates.get(agent, 0.0)
            lines.append(f"- `{agent}`: {count} actions, {rate:.1%} failure rate")
        if self.anomalies:
            lines += ["", "## ⚠️ Anomalies"]
            for a in self.anomalies:
                lines.append(f"- {a}")
        if self.consecutive_failure_agents:
            lines += ["", "## 🔴 Consecutive Failures"]
            for a in self.consecutive_failure_agents:
                lines.append(f"- {a}")
        return "\n".join(lines)
