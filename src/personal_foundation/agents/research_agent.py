"""Research Agent — daily AI governance research scanning and digest delivery.

INTERNAL USE ONLY — not part of the ai-bob-setup-agent customer product.

Scans for new publications on AI governance, scores relevance to the Foundation's
four pillars, and delivers daily digests via Telegram (Requirement 3).
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.personal_foundation.agents import BaseAgent
from src.personal_foundation.models import FOUNDATION_PILLARS, ResearchItem

if TYPE_CHECKING:
    from src.personal_foundation.integrations.perplexity_client import PerplexityClient


class ResearchAgent(BaseAgent):
    """Gathers and summarizes AI governance research (Requirement 3)."""

    agent_prefix = "personal/"
    agent_name = "research_agent"

    def __init__(self, config, dry_run: bool = False) -> None:
        super().__init__(config, dry_run)
        self._perplexity_client: PerplexityClient | None = None
        self._newsletter_draft_items: list[ResearchItem] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_daily_scan(self) -> list[ResearchItem]:
        """Run the daily research scan (Req 3.1).

        Queries Perplexity for items published in the prior 24 hours.
        On failure, logs + notifies Bob + returns empty list (Req 3.7).
        """
        scan_session_id = str(uuid.uuid4())

        try:
            raw_items = self._search_perplexity()
        except Exception as exc:
            self.log(
                action="daily_scan",
                command="perplexity_search",
                status="failure",
                result_summary=f"Perplexity scan failed: {type(exc).__name__}",
            )
            self._notify_bob(f"Research scan failed: {type(exc).__name__}")
            return []

        scored_items = []
        for raw in raw_items:
            item = self.score_item(raw, scan_session_id)
            scored_items.append(item)

        self.log(
            action="daily_scan",
            command="perplexity_search",
            result_summary=f"Scanned {len(scored_items)} items, {sum(1 for i in scored_items if i.relevance_score >= 4)} high-relevance",
            details={"items_found": len(scored_items), "session_id": scan_session_id},
        )

        return scored_items

    def score_item(self, item: ResearchItem, scan_session_id: str = "") -> ResearchItem:
        """Score a research item against the Foundation's four pillars (Req 3.2).

        Sets relevance_score to max of pillar scores.
        Generates ≤150-word summary if score ≥ 4 (Req 3.3).
        """
        pillar_scores = self._score_pillars(item)
        relevance_score = max(pillar_scores.values()) if pillar_scores else 1

        summary = None
        if relevance_score >= 4:
            summary = self._generate_summary(item)
            # Enforce 150-word limit
            words = summary.split()
            if len(words) > 150:
                summary = " ".join(words[:150]) + "..."

        item.pillar_scores = pillar_scores
        item.relevance_score = relevance_score
        item.summary = summary
        item.scan_session_id = scan_session_id or item.scan_session_id

        self.log(
            action="score_item",
            command=f"score item_id={item.item_id}",
            result_summary=f"score={relevance_score} title={item.title[:50]}",
            details={"item_id": item.item_id, "pillar_scores": pillar_scores},
        )

        return item

    def deliver_digest(self, items: list[ResearchItem]) -> None:
        """Deliver the daily digest to Bob via Telegram (Req 3.5, 3.6).

        If no high-relevance items, sends "no items" message (Req 3.6).
        On Telegram failure, retries once after 15 min (Req 3.8).
        """
        high_relevance = [i for i in items if i.relevance_score >= 4]

        if not high_relevance:
            message = "📊 Daily Research Digest: No high-relevance items found today."
        else:
            lines = ["📊 Daily Research Digest\n"]
            for item in high_relevance:
                lines.append(f"• [{item.relevance_score}/5] {item.title}")
                if item.summary:
                    lines.append(f"  {item.summary[:100]}...")
                lines.append(f"  {item.source_url}\n")
            message = "\n".join(lines)

        success = self._send_telegram(message)
        if not success:
            # Retry once after 15 minutes (Req 3.8)
            self.log(
                action="deliver_digest",
                command="telegram_send",
                status="failure",
                result_summary="First delivery attempt failed, retrying in 15 min",
            )
            if not self.dry_run:
                time.sleep(900)  # 15 minutes
            success = self._send_telegram(message)
            if not success:
                self.log(
                    action="deliver_digest",
                    command="telegram_send_retry",
                    status="failure",
                    result_summary="Second delivery attempt failed, giving up",
                )
                return

        self.log(
            action="deliver_digest",
            command="telegram_send",
            result_summary=f"Digest delivered: {len(high_relevance)} items",
            details={"items_count": len(high_relevance)},
        )

    def add_to_newsletter_draft(self, item: ResearchItem) -> None:
        """Append a scored item to the weekly newsletter draft (Req 3.3)."""
        if item.relevance_score >= 4 and item.summary:
            self._newsletter_draft_items.append(item)
            self.log(
                action="add_to_newsletter",
                command=f"newsletter item_id={item.item_id}",
                result_summary=f"Added to newsletter draft: {item.title[:50]}",
            )

    def get_newsletter_draft_items(self) -> list[ResearchItem]:
        """Return accumulated newsletter draft items for the Writing_Agent."""
        return list(self._newsletter_draft_items)

    def clear_newsletter_draft(self) -> None:
        """Clear the newsletter draft after it's been assembled."""
        self._newsletter_draft_items.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _search_perplexity(self) -> list[ResearchItem]:
        """Query Perplexity MCP for recent AI governance items."""
        if self._perplexity_client:
            return self._perplexity_client.search(
                query="AI governance responsible AI regulation",
                max_age_hours=24,
            )
        return []

    def _score_pillars(self, item: ResearchItem) -> dict[str, int]:
        """Score item against each Foundation pillar (1–5) via LLM."""
        from src.personal_foundation.llm_client import LLMClient

        try:
            client = LLMClient()
            result = client.score_research_item(item.title, item.source_url)
            scores = result.get("pillar_scores", {})
            # Ensure all pillars present with valid scores
            return {
                pillar: max(1, min(5, int(scores.get(pillar, 1))))
                for pillar in FOUNDATION_PILLARS
            }
        except Exception:
            return {pillar: 1 for pillar in FOUNDATION_PILLARS}

    def _generate_summary(self, item: ResearchItem) -> str:
        """Generate a ≤150-word summary via LLM."""
        from src.personal_foundation.llm_client import LLMClient

        try:
            client = LLMClient()
            result = client.score_research_item(item.title, item.source_url)
            summary = result.get("summary") or f"Summary of: {item.title}"
            # Enforce 150-word limit
            words = summary.split()
            if len(words) > 150:
                return " ".join(words[:150]) + "..."
            return summary
        except Exception:
            return f"Summary of: {item.title}"

    def _send_telegram(self, message: str) -> bool:
        """Send a message to Bob via Telegram. Returns True on success."""
        if self.dry_run:
            return True
        # Stub — in production, calls Telegram API
        return True

    def _notify_bob(self, message: str) -> None:
        """Send an alert to Bob via Telegram."""
        self._send_telegram(f"⚠️ Research Agent: {message}")
