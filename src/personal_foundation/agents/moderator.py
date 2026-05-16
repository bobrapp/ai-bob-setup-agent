"""Moderator — community content classification and flagging.

INTERNAL USE ONLY — not part of the ai-bob-setup-agent customer product.

Classifies posts for spam, toxicity, PII, scam links, and off-topic content.
Never auto-removes — all removal requires explicit approval (Requirement 8).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.personal_foundation.agents import BaseAgent
from src.personal_foundation.approval_queue import ApprovalItem
from src.personal_foundation.models import CirclePost

if TYPE_CHECKING:
    from src.personal_foundation.integrations.circle_client import CircleClient

# Confidence thresholds (Req 8.2–8.5)
SPAM_SCAM_THRESHOLD = 0.90
TOXIC_PII_THRESHOLD = 0.80
OFF_TOPIC_THRESHOLD = 0.85


@dataclass
class ClassificationResult:
    """Result of classifying a post across all dimensions."""

    spam: float = 0.0
    scam_link: float = 0.0
    toxicity: float = 0.0
    pii_exposure: float = 0.0
    off_topic: float = 0.0


class Moderator(BaseAgent):
    """Classifies and flags community content (Requirement 8).

    INVARIANT: Never calls delete or hide on any post. All removal
    requires explicit Approval_Queue approval (Req 8.7).
    """

    agent_prefix = "foundation/"
    agent_name = "moderator"

    def __init__(self, config, dry_run: bool = False) -> None:
        super().__init__(config, dry_run)
        self._circle_client: CircleClient | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify_post(self, post: CirclePost) -> ClassificationResult:
        """Classify a post across all moderation dimensions (Req 8.1).

        Returns confidence scores for each dimension.
        """
        result = self._call_llm_classify(post)

        self.log(
            action="classify",
            command=f"classify post_id={post.post_id}",
            result_summary=(
                f"spam={result.spam:.2f} toxic={result.toxicity:.2f} "
                f"pii={result.pii_exposure:.2f} off_topic={result.off_topic:.2f}"
            ),
            details={
                "post_id": post.post_id,
                "spam": result.spam,
                "scam_link": result.scam_link,
                "toxicity": result.toxicity,
                "pii_exposure": result.pii_exposure,
                "off_topic": result.off_topic,
            },
        )

        return result

    def act_on_classification(self, post: CirclePost, result: ClassificationResult) -> None:
        """Route based on confidence thresholds (Req 8.2–8.6).

        - spam/scam > 90% → flag + Telegram within 60s
        - toxic/PII > 80% → flag + Telegram within 5 min
        - off-topic > 85% → draft ≤280-char redirect → queue
        - below threshold → log only
        """
        # Spam or scam link (Req 8.2)
        if result.spam >= SPAM_SCAM_THRESHOLD or result.scam_link >= SPAM_SCAM_THRESHOLD:
            self._flag_and_notify_urgent(post, "spam/scam", max(result.spam, result.scam_link))
            return

        # Toxic or PII (Req 8.3)
        if result.toxicity >= TOXIC_PII_THRESHOLD or result.pii_exposure >= TOXIC_PII_THRESHOLD:
            self._flag_and_notify(post, "toxic/PII", max(result.toxicity, result.pii_exposure))
            return

        # Off-topic (Req 8.5)
        if result.off_topic >= OFF_TOPIC_THRESHOLD:
            self._draft_redirect(post, result.off_topic)
            return

        # Below all thresholds — log only (Req 8.6)
        self.log(
            action="below_threshold",
            command=f"no_action post_id={post.post_id}",
            result_summary="All scores below thresholds, no action taken",
            details={"post_id": post.post_id},
        )

    def classify_and_act(self, post: CirclePost, confidence_override: float | None = None) -> None:
        """Convenience method: classify then act. Used in tests."""
        result = self.classify_post(post)
        if confidence_override is not None:
            # For testing — override all scores with a single value
            result = ClassificationResult(
                spam=confidence_override,
                scam_link=0.0,
                toxicity=0.0,
                pii_exposure=0.0,
                off_topic=0.0,
            )
        self.act_on_classification(post, result)

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _flag_and_notify_urgent(self, post: CirclePost, category: str, confidence: float) -> None:
        """Flag post and notify via Telegram within 60 seconds (Req 8.2)."""
        # Flag in Circle.so
        if self._circle_client and not self.dry_run:
            self._circle_client.flag_post(post.post_id, f"Auto-flagged: {category} ({confidence:.0%})")

        # Notify via Telegram (Req 8.2 — within 60s)
        success = self._send_telegram_urgent(
            f"🚨 URGENT: Post flagged as {category} ({confidence:.0%})\n"
            f"Post ID: {post.post_id}\nTitle: {post.title[:50]}"
        )

        if not success:
            # Retry once after 60s (Req 8.4)
            self.log(
                action="notify_retry",
                command=f"telegram_retry post_id={post.post_id}",
                status="failure",
                result_summary="First notification failed, retrying in 60s",
            )
            if not self.dry_run:
                time.sleep(60)
            success = self._send_telegram_urgent(
                f"🚨 RETRY: Post flagged as {category} ({confidence:.0%})\n"
                f"Post ID: {post.post_id}"
            )
            if not success:
                self.log(
                    action="notify_failed",
                    command=f"telegram_final post_id={post.post_id}",
                    status="failure",
                    result_summary="Second notification also failed",
                )

        self.log(
            action="flag_urgent",
            command=f"flag post_id={post.post_id}",
            result_summary=f"Flagged as {category} ({confidence:.0%}), notified",
            details={"post_id": post.post_id, "category": category, "confidence": confidence},
        )

    def _flag_and_notify(self, post: CirclePost, category: str, confidence: float) -> None:
        """Flag post and notify via Telegram within 5 minutes (Req 8.3)."""
        if self._circle_client and not self.dry_run:
            self._circle_client.flag_post(post.post_id, f"Auto-flagged: {category} ({confidence:.0%})")

        success = self._send_telegram(
            f"⚠️ Post flagged as {category} ({confidence:.0%})\n"
            f"Post ID: {post.post_id}\nTitle: {post.title[:50]}"
        )

        if not success:
            # Retry once after 60s (Req 8.4)
            if not self.dry_run:
                time.sleep(60)
            success = self._send_telegram(
                f"⚠️ RETRY: Post flagged as {category} ({confidence:.0%})\n"
                f"Post ID: {post.post_id}"
            )
            if not success:
                self.log(
                    action="notify_failed",
                    command=f"telegram_final post_id={post.post_id}",
                    status="failure",
                    result_summary="Notification failed after retry",
                )

        self.log(
            action="flag",
            command=f"flag post_id={post.post_id}",
            result_summary=f"Flagged as {category} ({confidence:.0%})",
            details={"post_id": post.post_id, "category": category, "confidence": confidence},
        )

    def _draft_redirect(self, post: CirclePost, confidence: float) -> None:
        """Draft a ≤280-char redirect comment and queue (Req 8.5)."""
        redirect = self._compose_redirect(post)

        # Enforce 280-char limit
        if len(redirect) > 280:
            redirect = redirect[:277] + "..."

        item = ApprovalItem(
            agent=self.full_agent_name,
            action_type="redirect_comment",
            description=f"Redirect off-topic post: {post.title[:40]} ({confidence:.0%})",
            draft_content=redirect,
            rationale=f"Off-topic confidence: {confidence:.0%}",
        )
        self.queue(item)

        self.log(
            action="draft_redirect",
            command=f"redirect post_id={post.post_id}",
            result_summary=f"Redirect comment queued ({len(redirect)} chars)",
            details={"post_id": post.post_id, "confidence": confidence},
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call_llm_classify(self, post: CirclePost) -> ClassificationResult:
        """Call LLM to classify post. Stub for production model call."""
        return ClassificationResult()

    def _compose_redirect(self, post: CirclePost) -> str:
        """Compose a redirect comment (≤280 chars)."""
        return (
            f"Thanks for posting! This topic might get better engagement in a "
            f"different space. Our community focuses on AI governance — would you "
            f"like help finding the right place for this?"
        )

    def _send_telegram_urgent(self, message: str) -> bool:
        """Send urgent Telegram notification. Returns True on success."""
        if self.dry_run:
            return True
        return True  # Stub

    def _send_telegram(self, message: str) -> bool:
        """Send Telegram notification. Returns True on success."""
        if self.dry_run:
            return True
        return True  # Stub
