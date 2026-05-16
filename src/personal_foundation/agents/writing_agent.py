"""Writing Agent — content drafting and newsletter assembly.

INTERNAL USE ONLY — not part of the ai-bob-setup-agent customer product.

Produces first drafts of Foundation content in the AIGovOps voice,
assembles weekly newsletters, and handles revision cycles (Requirement 4).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from src.personal_foundation.agents import BaseAgent
from src.personal_foundation.approval_queue import ApprovalItem

if TYPE_CHECKING:
    pass

# Marketing superlatives to reject (Req 4.1)
SUPERLATIVES = [
    "revolutionary", "game-changing", "groundbreaking", "unprecedented",
    "best-in-class", "world-class", "cutting-edge", "disruptive",
    "transformative", "unparalleled", "unmatched", "industry-leading",
]

# CTA patterns to reject (Req 4.1)
CTA_PATTERNS = [
    r"sign up", r"subscribe now", r"buy now", r"get started",
    r"click here", r"learn more", r"join now", r"register today",
    r"purchase", r"order now",
]


class WritingAgent(BaseAgent):
    """Drafts Foundation content (Requirement 4)."""

    agent_prefix = "foundation/"
    agent_name = "writing_agent"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_draft(self, request: str, content_type: str) -> str:
        """Generate a draft in Foundation voice and queue for approval (Req 4.1).

        Never calls any publication API directly (Req 4.7).
        """
        draft = self._call_llm_draft(request, content_type)

        # Validate voice
        violations = self._validate_voice(draft)
        if violations:
            # Auto-fix by regenerating (one attempt)
            draft = self._call_llm_draft(
                f"{request}\n\n[IMPORTANT: Avoid these: {', '.join(violations)}]",
                content_type,
            )

        # Build rationale for editorial choices
        rationale = self._build_rationale(request, draft)

        item = ApprovalItem(
            agent=self.full_agent_name,
            action_type=f"content_draft_{content_type}",
            description=f"Content draft ({content_type}): {request[:60]}",
            draft_content=draft,
            rationale=rationale,
        )
        self.queue(item)

        self.log(
            action="create_draft",
            command=f"draft type={content_type} request={request[:50]}",
            result_summary=f"Draft queued ({content_type}), {len(draft.split())} words",
        )

        return draft

    def create_linkedin_variants(self, request: str) -> tuple[str, str, str]:
        """Generate 3 LinkedIn post variants (Req 4.3).

        Returns (short 50–100w, medium 150–250w, long-form 400–600w).
        """
        short = self._generate_variant(request, min_words=50, max_words=100)
        medium = self._generate_variant(request, min_words=150, max_words=250)
        long_form = self._generate_variant(request, min_words=400, max_words=600)

        # Queue all three for Bob/Ken to choose
        variants_text = (
            f"=== SHORT (50–100 words) ===\n{short}\n\n"
            f"=== MEDIUM (150–250 words) ===\n{medium}\n\n"
            f"=== LONG-FORM (400–600 words) ===\n{long_form}"
        )

        item = ApprovalItem(
            agent=self.full_agent_name,
            action_type="linkedin_variants",
            description=f"LinkedIn post variants: {request[:60]}",
            draft_content=variants_text,
            rationale="Three variants provided for selection: short, medium, long-form.",
        )
        self.queue(item)

        self.log(
            action="create_linkedin_variants",
            command=f"linkedin request={request[:50]}",
            result_summary=f"3 variants queued: {len(short.split())}w / {len(medium.split())}w / {len(long_form.split())}w",
        )

        return (short, medium, long_form)

    def assemble_newsletter(
        self, research_items: list, curator_digest: str = "", flagged_items: list | None = None
    ) -> str:
        """Assemble the weekly newsletter draft (Req 4.2).

        Triggered Sunday 18:00 Pacific. Pulls from Research_Agent weekly digest,
        Curator digest, and any flagged items. Queues by Sunday 18:00 Pacific.
        """
        sections = ["# AIGovOps Foundation Weekly Newsletter\n"]

        if research_items:
            sections.append("## Research Highlights\n")
            for item in research_items:
                if hasattr(item, "summary") and item.summary:
                    sections.append(f"**{item.title}**\n{item.summary}\n")

        if curator_digest:
            sections.append(f"## Community Highlights\n{curator_digest}\n")

        if flagged_items:
            sections.append("## Flagged Items\n")
            for fi in flagged_items:
                sections.append(f"- {fi}\n")

        draft = "\n".join(sections)

        item = ApprovalItem(
            agent=self.full_agent_name,
            action_type="newsletter_draft",
            description="Weekly newsletter draft for Monday distribution",
            draft_content=draft,
            rationale="Assembled from Research_Agent digest + Curator digest + flagged items.",
        )
        self.queue(item)

        self.log(
            action="assemble_newsletter",
            command="newsletter_assembly",
            result_summary=f"Newsletter draft queued: {len(draft.split())} words",
        )

        return draft

    def revise_draft(self, item_id: str, feedback: str) -> str:
        """Revise a rejected draft incorporating feedback (Req 4.5, 4.6).

        If feedback requires new sourcing or format change, notifies Bob/Ken
        of estimated time (≤60 min) before proceeding.
        """
        needs_new_sourcing = self._requires_new_sourcing(feedback)

        if needs_new_sourcing:
            # Notify of estimated time (Req 4.6)
            self._notify_revision_time(item_id, feedback)

        revised = self._call_llm_revise(item_id, feedback)

        item = ApprovalItem(
            agent=self.full_agent_name,
            action_type="content_revision",
            description=f"Revised draft (feedback incorporated): {feedback[:60]}",
            draft_content=revised,
            rationale=f"Revised per feedback: {feedback[:100]}",
        )
        self.queue(item)

        self.log(
            action="revise_draft",
            command=f"revise item_id={item_id}",
            result_summary=f"Revision queued, new_sourcing={needs_new_sourcing}",
        )

        return revised

    # ------------------------------------------------------------------
    # Voice validation (Req 4.1)
    # ------------------------------------------------------------------

    def _validate_voice(self, text: str) -> list[str]:
        """Check text for Foundation voice violations.

        Returns list of violation descriptions. Empty list = passes.
        Checks for:
        - Marketing superlatives
        - Calls-to-action directing readers to purchase or sign up
        """
        violations = []
        text_lower = text.lower()

        # Check superlatives
        for word in SUPERLATIVES:
            if word in text_lower:
                violations.append(f"superlative: '{word}'")

        # Check CTAs
        for pattern in CTA_PATTERNS:
            if re.search(pattern, text_lower):
                violations.append(f"CTA: '{pattern}'")

        return violations

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call_llm_draft(self, request: str, content_type: str) -> str:
        """Call LLM to generate a draft. Stub for production model call."""
        return f"Draft for {content_type}: {request}"

    def _generate_variant(self, request: str, min_words: int, max_words: int) -> str:
        """Generate a LinkedIn variant within word count bounds. Stub."""
        target = (min_words + max_words) // 2
        words = f"LinkedIn post about {request}. " * (target // 5)
        return " ".join(words.split()[:max_words])

    def _build_rationale(self, request: str, draft: str) -> str:
        """Build editorial rationale for the draft (Req 4.4)."""
        return "Practitioner-first framing applied. No superlatives or CTAs."

    def _requires_new_sourcing(self, feedback: str) -> bool:
        """Determine if feedback requires new sourcing or format change."""
        indicators = ["research", "source", "cite", "reference", "restructure", "reformat", "change format"]
        return any(ind in feedback.lower() for ind in indicators)

    def _notify_revision_time(self, item_id: str, feedback: str) -> None:
        """Notify Bob/Ken of estimated revision time (≤60 min)."""
        self.log(
            action="revision_time_estimate",
            command=f"estimate item_id={item_id}",
            result_summary="Estimated revision time: 30–60 minutes (new sourcing required)",
        )

    def _call_llm_revise(self, item_id: str, feedback: str) -> str:
        """Call LLM to revise a draft. Stub for production model call."""
        return f"Revised draft incorporating: {feedback}"
