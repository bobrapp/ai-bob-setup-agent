"""Task Agent — task tracking, project status, and outreach coordination.

INTERNAL USE ONLY — not part of the ai-bob-setup-agent customer product.

Manages Asana tasks, Trello sync, milestone alerts, weekly reports,
and outreach pipeline (Requirements 5, 9).
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from src.personal_foundation.agents import BaseAgent
from src.personal_foundation.approval_queue import ApprovalItem
from src.personal_foundation.models import OutreachContact, PipelineStage

if TYPE_CHECKING:
    from src.personal_foundation.integrations.composio_client import ComposioClient

MAX_OUTREACH_RETRIES = 3
OUTREACH_RETRY_INTERVAL_SECONDS = 60


class TaskAgent(BaseAgent):
    """Manages tasks, projects, and outreach (Requirements 5, 9)."""

    agent_prefix = "personal/"
    agent_name = "task_agent"

    def __init__(self, config, dry_run: bool = False) -> None:
        super().__init__(config, dry_run)
        self._composio_client: ComposioClient | None = None
        self._outreach_contacts: dict[str, OutreachContact] = {}

    # ------------------------------------------------------------------
    # Task management (Requirement 5)
    # ------------------------------------------------------------------

    def create_task_from_meeting(
        self, action_item: dict, meeting_ref: str
    ) -> None:
        """Create an Asana task from a meeting action item (Req 5.1).

        Default due date = 5 business days. Unresolved assignee → Bob with note.
        """
        assignee = action_item.get("assignee", "")
        resolved = self._resolve_assignee(assignee)
        due_date = action_item.get("due_date") or self._default_due_date()
        description = action_item.get("description", "Action item")

        notes = f"Source meeting: {meeting_ref}"
        if resolved != assignee and assignee:
            notes += f"\n[Assignee '{assignee}' not resolved — assigned to Bob]"

        task_data = {
            "name": description,
            "assignee": resolved,
            "due_date": due_date,
            "notes": notes,
        }

        if self._composio_client and not self.dry_run:
            self._composio_client.create_asana_task(task_data)

        self.log(
            action="create_task",
            command=f"asana_task from_meeting={meeting_ref}",
            result_summary=f"Task created: {description[:50]} → {resolved}",
        )

    def check_stale_tasks(self) -> list[str]:
        """Find tasks open > 7 days without updates, send reminders (Req 5.2).

        Returns list of task IDs that received reminders.
        """
        reminded = []
        if not self._composio_client:
            return reminded

        # In production, queries Asana for stale tasks
        stale_tasks = self._get_stale_tasks()

        for task in stale_tasks:
            assignee = task.get("assignee", "bob")
            self._send_reminder(assignee, task)
            reminded.append(task.get("id", ""))

        if reminded:
            self.log(
                action="stale_reminders",
                command="check_stale_tasks",
                result_summary=f"Sent {len(reminded)} stale task reminders",
            )

        return reminded

    def sync_trello_on_completion(self, asana_task_id: str) -> None:
        """Update Trello card when Asana task completes (Req 5.3).

        If no corresponding Trello card exists, logs and stops.
        """
        if not self._composio_client:
            return

        trello_card_id = self._find_trello_card(asana_task_id)
        if not trello_card_id:
            self.log(
                action="trello_sync_missing",
                command=f"trello_sync asana_id={asana_task_id}",
                status="partial",
                result_summary="No corresponding Trello card found",
                details={"asana_task_id": asana_task_id},
            )
            return

        if not self.dry_run:
            self._composio_client.update_trello_card(
                trello_card_id, {"status": "complete"}
            )

        self.log(
            action="trello_sync",
            command=f"trello_sync asana_id={asana_task_id}",
            result_summary=f"Trello card {trello_card_id} marked complete",
        )

    def milestone_morning_alert(self) -> None:
        """Send milestone alerts for items ≤ 3 days away (Req 5.4).

        Runs at 08:00 Pacific daily.
        """
        milestones = self._get_upcoming_milestones(days=3)
        if not milestones:
            return

        lines = ["📅 Milestone Alert\n"]
        for m in milestones:
            lines.append(
                f"• {m['name']} — due {m['due_date']} "
                f"({m.get('open_blocking', 0)} blocking tasks open)"
            )

        message = "\n".join(lines)
        self._send_telegram_to_both(message)

        self.log(
            action="milestone_alert",
            command="milestone_morning_alert",
            result_summary=f"Alerted on {len(milestones)} upcoming milestones",
        )

    def weekly_status_report(self) -> str:
        """Produce weekly project status report (Req 5.5).

        Triggered Friday 17:00 Pacific. Queues in Approval_Queue.
        """
        report = self._compile_status_report()

        item = ApprovalItem(
            agent=self.full_agent_name,
            action_type="weekly_status_report",
            description="Weekly project status report for distribution",
            draft_content=report,
        )
        self.queue(item)

        self.log(
            action="weekly_status_report",
            command="compile_report",
            result_summary=f"Weekly report queued ({len(report.split())} words)",
        )

        return report

    # ------------------------------------------------------------------
    # Outreach coordination (Requirement 9)
    # ------------------------------------------------------------------

    def add_outreach_contact(self, name: str, notes: str = "") -> OutreachContact:
        """Add a contact to the outreach pipeline (Req 9.1).

        Creates Asana task + queues first-contact draft.
        """
        import uuid

        contact_id = str(uuid.uuid4())
        contact = OutreachContact(
            contact_id=contact_id,
            name=name,
            pipeline_stage=PipelineStage.NEW,
            asana_task_id="",
            notes=notes,
        )

        # Create Asana task
        if self._composio_client and not self.dry_run:
            task_result = self._composio_client.create_asana_task({
                "name": f"Outreach: {name}",
                "notes": f"Pipeline stage: new\n{notes}",
                "due_date": self._default_due_date(),
            })
            contact.asana_task_id = task_result.get("id", contact_id)

        self._outreach_contacts[contact_id] = contact

        # Queue first-contact draft
        draft = self._generate_first_contact_draft(name, notes)
        item = ApprovalItem(
            agent=self.full_agent_name,
            action_type="outreach_first_contact",
            description=f"First contact message to {name}",
            draft_content=draft,
        )
        self.queue(item)

        self.log(
            action="add_outreach_contact",
            command=f"outreach_add name={name}",
            result_summary=f"Contact added, first-contact draft queued",
            details={"contact_id": contact_id, "name": name},
        )

        return contact

    def check_followup_due(self) -> list[str]:
        """Draft follow-ups for contacts with no interaction in 7 days (Req 9.2).

        Retries up to 3× at 60s intervals on failure.
        Returns list of contact IDs that received follow-up drafts.
        """
        followed_up = []
        now = datetime.now(timezone.utc)
        seven_days_ago = now - timedelta(days=7)

        for contact in self._outreach_contacts.values():
            if contact.pipeline_stage in (
                PipelineStage.RESPONDED_NOT_INTERESTED,
                PipelineStage.PARTNER_CONFIRMED,
                PipelineStage.ARCHIVED,
            ):
                continue

            if contact.last_contact_date and contact.last_contact_date > seven_days_ago:
                continue

            # Attempt draft with retries (Req 9.2)
            success = self._draft_followup_with_retry(contact)
            if success:
                followed_up.append(contact.contact_id)

        if followed_up:
            self.log(
                action="check_followup_due",
                command="outreach_followup_check",
                result_summary=f"Drafted {len(followed_up)} follow-ups",
            )

        return followed_up

    def draft_followup(self, contact: OutreachContact) -> str:
        """Draft a follow-up message for a contact. May raise on failure."""
        return self._generate_followup_draft(contact)

    def weekly_outreach_report(self) -> str:
        """Produce outreach status report (Req 9.6).

        Delivered to Bob via Telegram Friday 17:00 Pacific.
        """
        lines = ["📋 Outreach Status Report\n"]
        for contact in self._outreach_contacts.values():
            last_date = contact.last_contact_date.strftime("%Y-%m-%d") if contact.last_contact_date else "never"
            lines.append(
                f"• {contact.name} — {contact.pipeline_stage.value} (last: {last_date})"
            )

        report = "\n".join(lines) if len(lines) > 1 else "No active outreach contacts."
        self._send_telegram_to_bob(report)

        self.log(
            action="weekly_outreach_report",
            command="outreach_report",
            result_summary=f"Report delivered: {len(self._outreach_contacts)} contacts",
        )

        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _draft_followup_with_retry(self, contact: OutreachContact) -> bool:
        """Attempt to draft a follow-up, retrying up to 3 times (Req 9.2)."""
        for attempt in range(MAX_OUTREACH_RETRIES):
            try:
                draft = self._generate_followup_draft(contact)
                item = ApprovalItem(
                    agent=self.full_agent_name,
                    action_type="outreach_followup",
                    description=f"Follow-up to {contact.name} (7+ days since last contact)",
                    draft_content=draft,
                )
                self.queue(item)
                return True
            except Exception:
                if attempt < MAX_OUTREACH_RETRIES - 1:
                    if not self.dry_run:
                        time.sleep(OUTREACH_RETRY_INTERVAL_SECONDS)
                else:
                    # All retries exhausted (Req 9.2)
                    self.log(
                        action="followup_draft_failed",
                        command=f"outreach_followup contact={contact.name}",
                        status="failure",
                        result_summary=f"Draft failed after {MAX_OUTREACH_RETRIES} attempts",
                    )
                    self._notify_bob(f"Outreach follow-up draft failed for {contact.name}")
        return False

    def _generate_followup_draft(self, contact: OutreachContact) -> str:
        """Generate a follow-up message. Stub for LLM call."""
        return f"Hi {contact.name}, following up on our previous conversation..."

    def _generate_first_contact_draft(self, name: str, notes: str) -> str:
        """Generate a first-contact message. Stub for LLM call."""
        return f"Hi {name}, I'd like to introduce the AIGovOps Foundation..."

    def _resolve_assignee(self, assignee: str) -> str:
        """Resolve assignee name. Falls back to Bob."""
        return assignee if assignee else "bob"

    def _default_due_date(self) -> str:
        """5 business days from now."""
        due = datetime.now(timezone.utc)
        days_added = 0
        while days_added < 5:
            due += timedelta(days=1)
            if due.weekday() < 5:
                days_added += 1
        return due.strftime("%Y-%m-%d")

    def _get_stale_tasks(self) -> list[dict]:
        """Get tasks open > 7 days without updates. Stub."""
        return []

    def _find_trello_card(self, asana_task_id: str) -> str | None:
        """Find corresponding Trello card for an Asana task. Stub."""
        return None

    def _get_upcoming_milestones(self, days: int) -> list[dict]:
        """Get milestones due within N days. Stub."""
        return []

    def _compile_status_report(self) -> str:
        """Compile weekly status report. Stub."""
        return "# Weekly Project Status\n\nAll projects on track."

    def _send_reminder(self, assignee: str, task: dict) -> None:
        """Send stale task reminder via Telegram."""
        pass

    def _send_telegram_to_both(self, message: str) -> None:
        """Send message to both Bob and Ken."""
        pass

    def _send_telegram_to_bob(self, message: str) -> None:
        """Send message to Bob only."""
        pass

    def _notify_bob(self, message: str) -> None:
        """Send alert to Bob."""
        pass
