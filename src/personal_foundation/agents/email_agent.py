"""Email Agent — inbox triage and draft reply generation.

INTERNAL USE ONLY — not part of the ai-bob-setup-agent customer product.

Classifies incoming emails into 5 categories, drafts replies for action-required
items, and routes outreach responses through the pipeline (Requirements 1, 9.3–9.5).
"""

from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.personal_foundation.agents import BaseAgent
from src.personal_foundation.approval_queue import ApprovalItem
from src.personal_foundation.models import (
    EMAIL_CATEGORIES,
    EmailClassification,
    EmailMessage,
    PipelineStage,
)

if TYPE_CHECKING:
    from src.personal_foundation.integrations.composio_client import ComposioClient


class EmailAgent(BaseAgent):
    """Triages email and drafts replies (Requirement 1)."""

    agent_prefix = "personal/"
    agent_name = "email_agent"

    def __init__(self, config, dry_run: bool = False) -> None:
        super().__init__(config, dry_run)
        # Rate limiter: track timestamps of processed emails (Req 1.9)
        self._processed_timestamps: deque[float] = deque()
        self._composio_client: ComposioClient | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(self, email: EmailMessage) -> EmailClassification:
        """Classify an email into one of 5 categories with confidence score.

        Returns EmailClassification with category="" if confidence < 70%.
        """
        # In production, this calls an LLM. Here we define the interface contract.
        category, confidence = self._call_llm_classify(email)

        # Enforce exhaustiveness: if confidence >= 70%, category must be valid
        if confidence >= 0.70 and category not in EMAIL_CATEGORIES:
            # Fallback: flag for manual review (Req 1.6)
            category = ""
            confidence = 0.0

        subject_line = None
        if category == "action-required":
            subject_line = f"Re: {email.subject}"

        result = EmailClassification(
            category=category,
            confidence=confidence,
            subject_line=subject_line,
        )

        self.log(
            action="classify",
            command=f"classify email_id={email.message_id}",
            result_summary=f"category={category} confidence={confidence:.2f}",
            details={
                "email_id": email.message_id,
                "category": category,
                "confidence": confidence,
                "subject_line": subject_line,
            },
        )

        return result

    def process(self, email: EmailMessage) -> None:
        """Process a single email through the full triage pipeline.

        Routes based on classification result:
        - action-required → draft reply → Approval_Queue
        - FYI-only → archive + daily digest
        - newsletter → archive + extract to Research_Agent queue
        - spam → archive
        - foundation-business → Approval_Queue
        - low-confidence → flag for manual review
        """
        if not self._check_rate_limit():
            self.log(
                action="rate_limited",
                command=f"process email_id={email.message_id}",
                status="partial",
                result_summary="Rate limit reached (50/hr). Skipping.",
            )
            return

        self._record_processed()

        # Check if this is an outreach response first (Req 9.3–9.5)
        if email.is_outreach_contact and email.outreach_contact_id:
            self._handle_outreach_response(email)
            return

        classification = self.classify(email)

        if classification.confidence < 0.70 or classification.category == "":
            # Low confidence or unrecognized → flag for manual review (Req 1.5, 1.6)
            self._flag_for_manual_review(email, classification)
            return

        if classification.category == "action-required":
            self._handle_action_required(email, classification)
        elif classification.category == "FYI-only":
            self._handle_fyi(email)
        elif classification.category == "newsletter":
            self._handle_newsletter(email)
        elif classification.category == "spam":
            self._handle_spam(email)
        elif classification.category == "foundation-business":
            self._handle_foundation_business(email)

    def draft_reply(self, email: EmailMessage) -> str | None:
        """Generate a draft reply (subject line + body).

        Returns the draft text, or None on failure.
        On failure, the email is still queued with a failure note (Req 1.10).
        """
        try:
            draft = self._call_llm_draft(email)
            self.log(
                action="draft_reply",
                command=f"draft email_id={email.message_id}",
                result_summary=f"Draft generated for: {email.subject[:50]}",
            )
            return draft
        except Exception as exc:
            self.log(
                action="draft_reply",
                command=f"draft email_id={email.message_id}",
                status="failure",
                result_summary=f"Draft generation failed: {type(exc).__name__}",
            )
            return None

    # ------------------------------------------------------------------
    # Outreach response routing (Req 9.3–9.5)
    # ------------------------------------------------------------------

    def _handle_outreach_response(self, email: EmailMessage) -> None:
        """Classify outreach response and update pipeline stage."""
        response_type = self._classify_outreach_response(email)

        if response_type == "interested":
            self._update_pipeline_stage(
                email.outreach_contact_id, PipelineStage.RESPONDED_INTERESTED
            )
            # Create follow-up task in Asana
            self.log(
                action="outreach_response",
                command=f"outreach email_id={email.message_id}",
                result_summary=f"Contact interested, stage updated",
                details={"contact_id": email.outreach_contact_id, "response": "interested"},
            )
        elif response_type == "not-interested":
            self._update_pipeline_stage(
                email.outreach_contact_id, PipelineStage.RESPONDED_NOT_INTERESTED
            )
            self.log(
                action="outreach_response",
                command=f"outreach email_id={email.message_id}",
                result_summary=f"Contact not interested, archived",
                details={"contact_id": email.outreach_contact_id, "response": "not-interested"},
            )
        elif response_type == "needs-more-info":
            self._update_pipeline_stage(
                email.outreach_contact_id, PipelineStage.NEEDS_MORE_INFO
            )
            # Draft informational reply → Approval_Queue (Req 9.5)
            draft = self._call_llm_draft(email)
            item = ApprovalItem(
                agent=self.full_agent_name,
                action_type="outreach_reply",
                description=f"Informational reply to {email.sender} (needs more info)",
                draft_content=draft or f"[Draft failed for: {email.subject}]",
            )
            self.queue(item)
            self.log(
                action="outreach_response",
                command=f"outreach email_id={email.message_id}",
                result_summary=f"Contact needs more info, reply queued",
                details={"contact_id": email.outreach_contact_id, "response": "needs-more-info"},
            )

    # ------------------------------------------------------------------
    # Category handlers
    # ------------------------------------------------------------------

    def _handle_action_required(
        self, email: EmailMessage, classification: EmailClassification
    ) -> None:
        """Draft reply and queue for approval (Req 1.2, 1.10)."""
        draft = self.draft_reply(email)
        if draft:
            item = ApprovalItem(
                agent=self.full_agent_name,
                action_type="email_draft",
                description=f"Reply to: {email.subject[:80]} from {email.sender}",
                draft_content=draft,
            )
        else:
            # Draft failed — queue with failure note (Req 1.10)
            item = ApprovalItem(
                agent=self.full_agent_name,
                action_type="email_draft",
                description=f"Reply to: {email.subject[:80]} from {email.sender}",
                draft_content=f"[Draft generation failed. Please write reply from scratch.]\n\nOriginal subject: {email.subject}",
                rationale="Draft generation failed — flagged for manual reply.",
            )
        self.queue(item)

    def _handle_fyi(self, email: EmailMessage) -> None:
        """Archive and add to daily digest (Req 1.3)."""
        self.log(
            action="archive_fyi",
            command=f"archive email_id={email.message_id}",
            result_summary=f"FYI archived: {email.subject[:60]}",
        )

    def _handle_newsletter(self, email: EmailMessage) -> None:
        """Archive and extract relevant items to Research_Agent queue (Req 1.4)."""
        self.log(
            action="archive_newsletter",
            command=f"archive+extract email_id={email.message_id}",
            result_summary=f"Newsletter archived, items extracted: {email.subject[:50]}",
        )

    def _handle_spam(self, email: EmailMessage) -> None:
        """Archive spam (Req 1.1)."""
        self.log(
            action="archive_spam",
            command=f"archive email_id={email.message_id}",
            result_summary=f"Spam archived: {email.subject[:60]}",
        )

    def _handle_foundation_business(self, email: EmailMessage) -> None:
        """Queue foundation-business email for review."""
        item = ApprovalItem(
            agent=self.full_agent_name,
            action_type="foundation_email",
            description=f"Foundation business from {email.sender}: {email.subject[:60]}",
            draft_content=f"Subject: {email.subject}\nFrom: {email.sender}\nPreview: {email.body_preview[:200]}",
        )
        self.queue(item)

    def _flag_for_manual_review(
        self, email: EmailMessage, classification: EmailClassification
    ) -> None:
        """Flag low-confidence email for Bob's manual review (Req 1.5, 1.6)."""
        item = ApprovalItem(
            agent=self.full_agent_name,
            action_type="manual_review",
            description=f"Low-confidence email from {email.sender}: {email.subject[:60]}",
            draft_content=f"[No draft generated — confidence {classification.confidence:.0%}]\n\nSubject: {email.subject}\nFrom: {email.sender}",
            rationale=f"Classification confidence {classification.confidence:.0%} below 70% threshold.",
        )
        self.queue(item)

    # ------------------------------------------------------------------
    # Rate limiting (Req 1.9)
    # ------------------------------------------------------------------

    def _check_rate_limit(self) -> bool:
        """Return True if we can process another email this hour."""
        now = time.time()
        one_hour_ago = now - 3600
        # Remove old timestamps
        while self._processed_timestamps and self._processed_timestamps[0] < one_hour_ago:
            self._processed_timestamps.popleft()
        return len(self._processed_timestamps) < self.config.max_emails_per_hour

    def _record_processed(self) -> None:
        """Record that an email was processed."""
        self._processed_timestamps.append(time.time())

    # ------------------------------------------------------------------
    # LLM stubs (to be wired to actual model calls)
    # ------------------------------------------------------------------

    def _call_llm_classify(self, email: EmailMessage) -> tuple[str, float]:
        """Call LLM to classify email. Returns (category, confidence).

        Override or mock in tests. Production implementation calls GPT 5.5.
        """
        # Default stub — in production, this calls the model
        return ("action-required", 0.85)

    def _call_llm_draft(self, email: EmailMessage) -> str:
        """Call LLM to draft a reply. Returns draft text.

        Override or mock in tests. Production implementation calls GPT 5.5.
        """
        return f"Re: {email.subject}\n\nThank you for your email. I'll review and respond shortly."

    def _classify_outreach_response(self, email: EmailMessage) -> str:
        """Classify outreach response as interested/not-interested/needs-more-info.

        Override or mock in tests.
        """
        return "interested"

    def _update_pipeline_stage(
        self, contact_id: str | None, stage: PipelineStage
    ) -> None:
        """Update the outreach contact's pipeline stage via Composio."""
        if not contact_id:
            return
        if self._composio_client and not self.dry_run:
            self._composio_client.update_asana_task(
                contact_id, {"pipeline_stage": stage.value}
            )
