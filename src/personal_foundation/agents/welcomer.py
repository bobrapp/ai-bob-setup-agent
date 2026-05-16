"""Welcomer — Circle.so new member onboarding.

INTERNAL USE ONLY — not part of the ai-bob-setup-agent customer product.

Sends personalized welcome DMs, posts to the welcome thread, and applies
interest tags to new community members (Requirement 6).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.personal_foundation.agents import BaseAgent
from src.personal_foundation.models import CircleMember

if TYPE_CHECKING:
    from src.personal_foundation.integrations.circle_client import CircleClient

# Mapping of keywords to Circle.so interest tags
INTEREST_TAG_MAP = {
    "governance as code": "governance-as-code",
    "ai technical debt": "ai-technical-debt",
    "operational compliance": "operational-compliance",
    "community standards": "community-driven-standards",
    "responsible ai": "responsible-ai",
    "ai regulation": "ai-regulation",
    "ai ethics": "ai-ethics",
    "mlops": "mlops",
    "model governance": "model-governance",
}


class Welcomer(BaseAgent):
    """Welcomes new Circle.so community members (Requirement 6)."""

    agent_prefix = "foundation/"
    agent_name = "welcomer"

    def __init__(self, config, dry_run: bool = False) -> None:
        super().__init__(config, dry_run)
        self._circle_client: CircleClient | None = None
        # Track sent DMs for idempotency (Req 6.5)
        self._sent_dms: set[tuple[str, str]] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def welcome(self, member_id: str, join_event_id: str) -> None:
        """Run the full welcome flow for a new member (Req 6.1–6.6).

        Idempotent: checks for prior DM before sending (Req 6.5).
        """
        # Idempotency check (Req 6.5)
        if self._has_already_welcomed(member_id, join_event_id):
            self.log(
                action="welcome_skipped",
                command=f"welcome member_id={member_id}",
                result_summary="Already welcomed (idempotency check)",
                details={"member_id": member_id, "join_event_id": join_event_id},
            )
            return

        # Fetch member profile
        member = self._get_member(member_id)

        # Send welcome DM (Req 6.1)
        self.send_welcome_dm(member, join_event_id)

        # Post to welcome thread (Req 6.2)
        self.post_welcome_thread(member)

        # Apply interest tags (Req 6.3)
        self.apply_interest_tags(member)

    def send_welcome_dm(self, member: CircleMember, join_event_id: str) -> None:
        """Send a personalized welcome DM (Req 6.1).

        References at least one specific detail from the member's profile.
        """
        personalization = self._select_personalization(member)
        body = self._compose_welcome_dm(member, personalization)

        success = self._send_dm_with_backoff(member.member_id, body)

        if success:
            # Record for idempotency
            self._sent_dms.add((member.member_id, join_event_id))

            self.log(
                action="send_dm",
                command=f"welcome_dm member_id={member.member_id}",
                result_summary=f"Welcome DM sent to {member.member_id}",
                details={
                    "member_id": member.member_id,
                    "join_event_id": join_event_id,
                    "personalization": personalization,
                },
            )

    def post_welcome_thread(self, member: CircleMember) -> None:
        """Post a welcome message in the community welcome thread (Req 6.2)."""
        resource = self._match_community_resource(member)
        body = (
            f"Welcome to the AIGovOps Foundation community, @{member.display_name}! 🎉\n\n"
            f"We're glad to have you here. "
            f"Check out {resource} — it's a great place to start based on your interests."
        )

        if self._circle_client and not self.dry_run:
            self._circle_client.post_to_space(
                self.config.circle.welcome_space_id,
                body=body,
                title=f"Welcome {member.display_name}!",
            )

        self.log(
            action="welcome_thread_post",
            command=f"welcome_post member_id={member.member_id}",
            result_summary=f"Welcome thread post for {member.member_id}",
            details={"member_id": member.member_id, "resource": resource},
        )

    def apply_interest_tags(self, member: CircleMember) -> None:
        """Map profile keywords to interest tags and apply them (Req 6.3)."""
        profile_text = f"{member.bio} {member.role} {' '.join(member.ai_governance_interests)}".lower()

        applied_tags = []
        for keyword, tag in INTEREST_TAG_MAP.items():
            if keyword in profile_text:
                if self._circle_client and not self.dry_run:
                    self._circle_client.apply_tag(member.member_id, tag)
                applied_tags.append(tag)

        if applied_tags:
            self.log(
                action="apply_tags",
                command=f"tags member_id={member.member_id}",
                result_summary=f"Applied {len(applied_tags)} tags",
                details={"member_id": member.member_id, "tags": applied_tags},
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _has_already_welcomed(self, member_id: str, join_event_id: str) -> bool:
        """Check if we've already sent a DM for this member+event (Req 6.5)."""
        return (member_id, join_event_id) in self._sent_dms

    def _get_member(self, member_id: str) -> CircleMember:
        """Fetch member profile from Circle.so."""
        if self._circle_client:
            return self._circle_client.get_member(member_id)
        return CircleMember(member_id=member_id, display_name="Member")

    def _select_personalization(self, member: CircleMember) -> str:
        """Select a personalization element from the member's profile."""
        if member.role:
            return f"role: {member.role}"
        if member.organization:
            return f"organization: {member.organization}"
        if member.ai_governance_interests:
            return f"interest: {member.ai_governance_interests[0]}"
        if member.bio:
            return f"bio mention: {member.bio[:50]}"
        return "new member"

    def _compose_welcome_dm(self, member: CircleMember, personalization: str) -> str:
        """Compose the welcome DM body."""
        name = member.display_name or "there"
        return (
            f"Hi {name}! 👋\n\n"
            f"Welcome to the AIGovOps Foundation community. "
            f"I noticed your {personalization} — that's exactly the kind of "
            f"perspective we value here.\n\n"
            f"Feel free to introduce yourself in the welcome thread, and don't "
            f"hesitate to reach out if you have questions.\n\n"
            f"— Bob & Ken, AIGovOps Foundation"
        )

    def _match_community_resource(self, member: CircleMember) -> str:
        """Match a community resource to the member's interests."""
        profile_text = f"{member.bio} {member.role}".lower()
        if "governance" in profile_text:
            return "our Governance as Code discussion space"
        if "compliance" in profile_text:
            return "our Operational Compliance resources"
        if "technical debt" in profile_text:
            return "our AI Technical Debt working group"
        return "our Getting Started guide"

    def _send_dm_with_backoff(self, member_id: str, body: str) -> bool:
        """Send DM with exponential backoff on Circle.so API failure (Req 6.4).

        Starts at 30s, doubles each attempt, max 30-min window.
        On exhaustion, logs failure + notifies Bob.
        """
        if self.dry_run:
            return True

        if not self._circle_client:
            return False

        try:
            self._circle_client.with_exponential_backoff(
                self._circle_client.send_dm,
                member_id,
                body,
                initial_delay=30.0,
                max_window_seconds=1800.0,
            )
            return True
        except Exception as exc:
            self.log(
                action="dm_backoff_exhausted",
                command=f"send_dm member_id={member_id}",
                status="failure",
                result_summary=f"DM failed after 30-min backoff: {type(exc).__name__}",
            )
            self._notify_bob(f"Welcome DM failed for member {member_id}")
            return False

    def _notify_bob(self, message: str) -> None:
        """Send alert to Bob via Telegram."""
        pass  # Wired in production via Orchestrator
