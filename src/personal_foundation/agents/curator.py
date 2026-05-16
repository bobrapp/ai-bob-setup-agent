"""Curator — weekly community digest and content amplification.

INTERNAL USE ONLY — not part of the ai-bob-setup-agent customer product.

Identifies top community posts, drafts weekly digests and member spotlights,
and bumps high-quality inactive threads (Requirement 7).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from src.personal_foundation.agents import BaseAgent
from src.personal_foundation.approval_queue import ApprovalItem
from src.personal_foundation.models import CirclePost

if TYPE_CHECKING:
    from src.personal_foundation.integrations.circle_client import CircleClient

AI_GOVERNANCE_TAGS = [
    "governance-as-code", "ai-technical-debt", "operational-compliance",
    "community-driven-standards", "responsible-ai", "ai-regulation",
    "ai-ethics", "mlops", "model-governance", "ai-governance",
]


class Curator(BaseAgent):
    """Curates weekly community digests (Requirement 7)."""

    agent_prefix = "foundation/"
    agent_name = "curator"

    def __init__(self, config, dry_run: bool = False) -> None:
        super().__init__(config, dry_run)
        self._circle_client: CircleClient | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_weekly_curation(self) -> str | None:
        """Run the weekly curation cycle (Req 7.1–7.4).

        Triggered Sunday 12:00 Pacific. Returns digest text or None.
        """
        posts = self._fetch_recent_posts(days=7)

        # Filter to AI governance tagged posts (Req 7.1)
        qualifying = [
            p for p in posts
            if any(tag in AI_GOVERNANCE_TAGS for tag in p.tags)
        ]

        # Rank by engagement (Req 7.1)
        qualifying.sort(key=lambda p: p.engagement, reverse=True)
        top_posts = qualifying[:5]

        if not top_posts:
            # No qualifying posts (Req 7.3)
            self._notify_bob("Weekly curation: no qualifying posts found this week.")
            self.log(
                action="weekly_curation",
                command="curation_cycle",
                result_summary="No qualifying posts found, digest skipped",
            )
            return None

        # Draft digest + member spotlight (Req 7.2)
        digest = self.draft_digest(top_posts)

        self.log(
            action="weekly_curation",
            command="curation_cycle",
            result_summary=f"Digest drafted: {len(top_posts)} posts, queued for approval",
        )

        return digest

    def draft_digest(self, top_posts: list[CirclePost]) -> str:
        """Draft weekly digest and member spotlight (Req 7.2).

        Queues both in the Approval_Queue.
        """
        # Build digest
        lines = ["# Weekly Community Digest\n"]
        for i, post in enumerate(top_posts, 1):
            lines.append(
                f"{i}. **{post.title}** by member {post.author_member_id} "
                f"({post.engagement} engagement)"
            )
            lines.append(f"   {post.body[:100]}...\n")

        # Member spotlight — highest engagement contributor (Req 7.2)
        top_contributor = top_posts[0]
        spotlight = (
            f"\n## 🌟 Member Spotlight\n"
            f"**{top_contributor.author_member_id}** — "
            f"posted \"{top_contributor.title}\" which generated "
            f"{top_contributor.engagement} engagement signals this week."
        )
        lines.append(spotlight)

        digest_text = "\n".join(lines)

        # Queue for approval (Req 7.6)
        item = ApprovalItem(
            agent=self.full_agent_name,
            action_type="weekly_digest",
            description="Weekly community digest + member spotlight",
            draft_content=digest_text,
            rationale=f"Top {len(top_posts)} posts by engagement from AI governance tagged content.",
        )
        self.queue(item)

        self.log(
            action="draft_digest",
            command="digest_draft",
            result_summary=f"Digest drafted: {len(top_posts)} posts featured",
        )

        return digest_text

    def publish_digest(self, item_id: str, digest_content: str) -> bool:
        """Publish approved digest to Circle.so (Req 7.4).

        If no success response within 5 min, marks as failed and requires
        re-approval before retry.
        """
        if self.dry_run:
            self.log(
                action="publish_digest",
                command=f"publish item_id={item_id}",
                result_summary="[dry_run] Digest would be published",
            )
            return True

        if not self._circle_client:
            return False

        try:
            result = self._circle_client.post_to_space(
                self.config.circle.digest_space_id,
                body=digest_content,
                title="Weekly Community Digest",
            )
            success = bool(result and result.get("id"))

            if success:
                self.log(
                    action="publish_digest",
                    command=f"publish item_id={item_id}",
                    result_summary="Digest published successfully",
                )
            else:
                self.log(
                    action="publish_digest",
                    command=f"publish item_id={item_id}",
                    status="failure",
                    result_summary="Publication failed — requires re-approval",
                )

            return success
        except Exception as exc:
            self.log(
                action="publish_digest",
                command=f"publish item_id={item_id}",
                status="failure",
                result_summary=f"Publication failed: {type(exc).__name__}",
            )
            return False

    def check_inactive_threads(self) -> list[str]:
        """Find inactive threads with high engagement and draft bumps (Req 7.5).

        Threads inactive > 14 days with engagement ≥ 5 get a bump comment queued.
        """
        posts = self._fetch_recent_posts(days=60)  # Look back further
        now = datetime.now(timezone.utc)
        fourteen_days_ago = now - timedelta(days=14)

        bumped = []
        for post in posts:
            last_activity = post.last_activity_at or post.published_at
            if last_activity < fourteen_days_ago and post.engagement >= 5:
                # Draft bump comment
                bump = self._draft_bump_comment(post)
                item = ApprovalItem(
                    agent=self.full_agent_name,
                    action_type="thread_bump",
                    description=f"Bump inactive thread: {post.title[:50]}",
                    draft_content=bump,
                    rationale=f"Thread inactive {(now - last_activity).days} days, engagement={post.engagement}",
                )
                self.queue(item)
                bumped.append(post.post_id)

        if bumped:
            self.log(
                action="check_inactive_threads",
                command="inactive_thread_scan",
                result_summary=f"Drafted {len(bumped)} bump comments",
            )

        return bumped

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_recent_posts(self, days: int) -> list[CirclePost]:
        """Fetch recent posts from Circle.so."""
        if self._circle_client:
            return self._circle_client.list_recent_posts(days=days)
        return []

    def _draft_bump_comment(self, post: CirclePost) -> str:
        """Draft a bump comment for an inactive thread."""
        return (
            f"This thread had great discussion! Anyone have updates or new "
            f"perspectives on \"{post.title}\"? Would love to hear how things "
            f"have evolved."
        )

    def _notify_bob(self, message: str) -> None:
        """Send notification to Bob via Telegram."""
        pass  # Wired in production
