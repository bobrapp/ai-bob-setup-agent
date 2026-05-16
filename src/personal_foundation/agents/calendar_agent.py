"""Calendar Agent — scheduling and meeting preparation.

INTERNAL USE ONLY — not part of the ai-bob-setup-agent customer product.

Handles meeting requests, generates briefings, extracts action items from
Granola notes, and manages recurring meeting context (Requirement 2).
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from src.personal_foundation.agents import BaseAgent
from src.personal_foundation.approval_queue import ApprovalItem
from src.personal_foundation.models import MeetingBriefing, MeetingNotes

if TYPE_CHECKING:
    from src.personal_foundation.integrations.composio_client import ComposioClient
    from src.personal_foundation.integrations.granola_client import GranolaClient


class CalendarAgent(BaseAgent):
    """Manages scheduling and meeting preparation (Requirement 2)."""

    agent_prefix = "personal/"
    agent_name = "calendar_agent"

    def __init__(self, config, dry_run: bool = False) -> None:
        super().__init__(config, dry_run)
        self._granola_client: GranolaClient | None = None
        self._composio_client: ComposioClient | None = None
        # Running context documents for recurring meetings
        self._recurring_contexts: dict[str, list[dict]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def handle_meeting_request(
        self, requested_time: datetime, attendees: list[str], subject: str
    ) -> None:
        """Handle an incoming meeting request (Req 2.1, 2.2).

        If the slot is unavailable, proposes 3 alternatives within next 5
        business days between 09:00–18:00 Pacific.
        """
        available = self._check_availability(requested_time)

        if available:
            # Slot available — queue confirmation (Req 2.2)
            item = ApprovalItem(
                agent=self.full_agent_name,
                action_type="calendar_confirm",
                description=f"Confirm meeting: {subject} at {requested_time.strftime('%Y-%m-%d %H:%M')}",
                draft_content=f"Meeting: {subject}\nTime: {requested_time}\nAttendees: {', '.join(attendees)}",
            )
            self.queue(item)
        else:
            # Unavailable — propose 3 alternatives (Req 2.1)
            alternatives = self._propose_alternatives(requested_time)
            alt_text = "\n".join(
                f"  {i+1}. {t.strftime('%A %Y-%m-%d %H:%M')}" for i, t in enumerate(alternatives)
            )
            item = ApprovalItem(
                agent=self.full_agent_name,
                action_type="calendar_reschedule",
                description=f"Reschedule: {subject} (requested slot unavailable)",
                draft_content=f"Meeting: {subject}\nRequested: {requested_time} (unavailable)\n\nProposed alternatives:\n{alt_text}",
            )
            self.queue(item)

        self.log(
            action="handle_meeting_request",
            command=f"meeting_request subject={subject[:50]}",
            result_summary=f"{'Confirmed' if available else '3 alternatives proposed'}",
        )

    def generate_briefing(
        self, meeting_id: str, attendees: list[str], subject: str
    ) -> MeetingBriefing:
        """Generate a pre-meeting briefing document (Req 2.3).

        Fetches 5 most recent Granola notes with overlapping attendees,
        compiles attendee backgrounds, and generates a suggested agenda.
        """
        recent_notes = self._fetch_recent_notes_for_attendees(attendees)
        backgrounds = self._compile_attendee_backgrounds(attendees, recent_notes)
        agenda = self._generate_agenda(subject, recent_notes)

        briefing = MeetingBriefing(
            meeting_id=meeting_id,
            attendee_backgrounds=backgrounds,
            recent_notes=recent_notes[:5],
            suggested_agenda=agenda,
        )

        self.log(
            action="generate_briefing",
            command=f"briefing meeting_id={meeting_id}",
            result_summary=f"Briefing generated: {len(backgrounds)} attendees, {len(recent_notes)} notes",
        )

        return briefing

    def post_meeting_followup(self, meeting_id: str) -> None:
        """Extract action items from Granola notes and create Asana tasks (Req 2.4).

        Unresolved assignees default to Bob with a note.
        """
        notes = self._get_meeting_notes(meeting_id)
        if not notes:
            self.log(
                action="post_meeting_followup",
                command=f"followup meeting_id={meeting_id}",
                status="partial",
                result_summary="No Granola notes found for meeting",
            )
            return

        for action_item in notes.action_items:
            assignee = action_item.get("assignee", "")
            resolved_assignee = self._resolve_assignee(assignee)
            due_date = action_item.get("due_date") or self._default_due_date()

            task_data = {
                "name": action_item.get("description", "Action item"),
                "assignee": resolved_assignee,
                "due_date": due_date,
                "notes": f"Source: {notes.title} ({notes.date.strftime('%Y-%m-%d')})",
            }

            if resolved_assignee != assignee and assignee:
                task_data["notes"] += f"\n[Note: Original assignee '{assignee}' could not be resolved to an Asana user. Assigned to Bob.]"

            if self._composio_client and not self.dry_run:
                self._composio_client.create_asana_task(task_data)

        self.log(
            action="post_meeting_followup",
            command=f"followup meeting_id={meeting_id}",
            result_summary=f"Created {len(notes.action_items)} tasks from meeting notes",
        )

    def update_recurring_context(self, series_id: str, session_notes: MeetingNotes) -> None:
        """Append session decisions and action items to the series context (Req 2.5)."""
        if series_id not in self._recurring_contexts:
            self._recurring_contexts[series_id] = []

        entry = {
            "date": session_notes.date.isoformat(),
            "title": session_notes.title,
            "action_items": session_notes.action_items,
            "summary": session_notes.summary,
        }
        self._recurring_contexts[series_id].append(entry)

        self.log(
            action="update_recurring_context",
            command=f"recurring series_id={series_id}",
            result_summary=f"Context updated: {len(self._recurring_contexts[series_id])} sessions",
        )

    def handle_cancellation(self, meeting_id: str, subject: str) -> None:
        """Handle a meeting cancelled within 2 hours of start (Req 2.6).

        Releases time block, suggests alternative use, notifies via Telegram.
        """
        alternatives = ["focused work", "admin catch-up", "rest"]
        suggestion = random.choice(alternatives)

        self.log(
            action="handle_cancellation",
            command=f"cancellation meeting_id={meeting_id}",
            result_summary=f"Time released, suggested: {suggestion}",
        )

        # Attempt Telegram notification
        try:
            if not self.dry_run:
                self._notify_cancellation(meeting_id, subject, suggestion)
        except Exception as exc:
            # Log failure without blocking (Req 2.6)
            self.log(
                action="cancellation_notify_failed",
                command=f"telegram notify meeting_id={meeting_id}",
                status="failure",
                result_summary=f"Telegram notification failed: {type(exc).__name__}",
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_availability(self, requested_time: datetime) -> bool:
        """Check if the requested time slot is available. Stub for calendar API."""
        return True  # Override in production

    def _propose_alternatives(self, around: datetime) -> list[datetime]:
        """Propose 3 alternative times within next 5 business days, 09:00–18:00."""
        alternatives = []
        current = around + timedelta(hours=1)
        attempts = 0
        while len(alternatives) < 3 and attempts < 50:
            attempts += 1
            # Skip weekends
            if current.weekday() >= 5:
                current += timedelta(days=1)
                current = current.replace(hour=9, minute=0)
                continue
            # Enforce 09:00–18:00
            if current.hour < 9:
                current = current.replace(hour=9, minute=0)
            elif current.hour >= 18:
                current += timedelta(days=1)
                current = current.replace(hour=9, minute=0)
                continue
            # Check within 5 business days
            if (current - around).days > 7:
                break
            alternatives.append(current)
            current += timedelta(hours=2)
        return alternatives

    def _fetch_recent_notes_for_attendees(self, attendees: list[str]) -> list[dict]:
        """Fetch up to 5 most recent Granola notes with overlapping attendees."""
        # Stub — in production, queries GranolaClient
        return []

    def _compile_attendee_backgrounds(
        self, attendees: list[str], notes: list[dict]
    ) -> list[dict[str, str]]:
        """Compile attendee backgrounds from prior notes and public profiles."""
        return [{"name": a, "background": ""} for a in attendees]

    def _generate_agenda(self, subject: str, notes: list[dict]) -> list[str]:
        """Generate a suggested agenda based on subject and prior context."""
        return [f"Discuss: {subject}", "Review action items from last session", "Next steps"]

    def _get_meeting_notes(self, meeting_id: str) -> MeetingNotes | None:
        """Retrieve Granola meeting notes."""
        if self._granola_client:
            return self._granola_client.get_meeting_notes(meeting_id)
        return None

    def _resolve_assignee(self, assignee: str) -> str:
        """Resolve an assignee name to an Asana user. Falls back to Bob."""
        # Stub — in production, looks up Asana users
        if not assignee:
            return "bob"
        return assignee

    def _default_due_date(self) -> str:
        """Return a due date 5 business days from now."""
        due = datetime.now(timezone.utc)
        days_added = 0
        while days_added < 5:
            due += timedelta(days=1)
            if due.weekday() < 5:
                days_added += 1
        return due.strftime("%Y-%m-%d")

    def _notify_cancellation(self, meeting_id: str, subject: str, suggestion: str) -> None:
        """Send cancellation notification via Telegram."""
        # Stub — in production, calls Telegram API
        pass
