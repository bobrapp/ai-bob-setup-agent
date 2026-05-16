"""Batch processor — processes multiple items in a single LLM call.

Instead of classifying 10 emails one-by-one (10 API calls), batches them
into a single call (1 API call). 10x cost reduction for high-volume agents.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from litellm import acompletion

from src.personal_foundation.v2.state import StateStore
from src.personal_foundation.v2.cost_tracker import CostTracker

log = logging.getLogger(__name__)

MAX_BATCH_SIZE = 10
BATCH_MODEL = "groq/llama-3.1-70b-versatile"  # Fast + cheap for batch classification


class BatchProcessor:
    """Processes multiple items in a single LLM call."""

    def __init__(self, store: StateStore, dry_run: bool = False) -> None:
        self.store = store
        self.dry_run = dry_run
        self.cost_tracker = CostTracker(store)

    async def classify_emails_batch(self, emails: list[dict]) -> list[dict]:
        """Classify multiple emails in one LLM call.

        Args:
            emails: List of {sender, subject, preview} dicts (max 10)

        Returns:
            List of {category, confidence} dicts in same order
        """
        if not emails:
            return []

        batch = emails[:MAX_BATCH_SIZE]

        if self.dry_run:
            return [{"category": "FYI-only", "confidence": 0.5} for _ in batch]

        # Build batch prompt
        email_list = "\n".join(
            f"[{i+1}] From: {e.get('sender','')} | Subject: {e.get('subject','')} | Preview: {e.get('preview','')[:100]}"
            for i, e in enumerate(batch)
        )

        system = (
            "Classify each email into exactly one category per line:\n"
            "Categories: action-required, FYI-only, newsletter, spam, foundation-business\n\n"
            "Respond with JSON array: [{\"index\": 1, \"category\": \"...\", \"confidence\": 0.0-1.0}, ...]"
        )

        try:
            response = await acompletion(
                model=BATCH_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"Classify these {len(batch)} emails:\n\n{email_list}"},
                ],
                temperature=0.1,
                max_tokens=512,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            parsed = json.loads(content)

            # Track cost
            if response.usage:
                self.cost_tracker.record(
                    "personal/email_classifier", BATCH_MODEL,
                    response.usage.prompt_tokens, response.usage.completion_tokens,
                )

            # Normalize results
            if isinstance(parsed, dict) and "results" in parsed:
                results = parsed["results"]
            elif isinstance(parsed, list):
                results = parsed
            else:
                results = [{"category": "FYI-only", "confidence": 0.5}] * len(batch)

            # Ensure we have one result per email
            while len(results) < len(batch):
                results.append({"category": "FYI-only", "confidence": 0.5})

            log.info("BatchProcessor: classified %d emails in 1 call", len(batch))
            return results[:len(batch)]

        except Exception as exc:
            log.error("BatchProcessor: batch classification failed: %s", exc)
            return [{"category": "", "confidence": 0.0} for _ in batch]

    async def score_research_batch(self, items: list[dict]) -> list[dict]:
        """Score multiple research items in one LLM call.

        Args:
            items: List of {title, url} dicts (max 10)

        Returns:
            List of {pillar_scores, relevance_score, summary} dicts
        """
        if not items:
            return []

        batch = items[:MAX_BATCH_SIZE]

        if self.dry_run:
            return [{"pillar_scores": {}, "relevance_score": 1, "summary": None} for _ in batch]

        item_list = "\n".join(
            f"[{i+1}] {it.get('title','')} — {it.get('url','')}"
            for i, it in enumerate(batch)
        )

        system = (
            "Score each item's relevance to AIGovOps Foundation pillars (1-5 each):\n"
            "- governance_as_code\n- ai_technical_debt\n- operational_compliance\n- community_driven_standards\n\n"
            "For items with max score ≥4, provide a 1-sentence summary.\n"
            "Respond with JSON array: [{\"index\": 1, \"scores\": {...}, \"max_score\": N, \"summary\": \"...\" or null}, ...]"
        )

        try:
            response = await acompletion(
                model=BATCH_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"Score these {len(batch)} items:\n\n{item_list}"},
                ],
                temperature=0.2,
                max_tokens=1024,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            parsed = json.loads(content)

            if response.usage:
                self.cost_tracker.record(
                    "personal/research_scanner", BATCH_MODEL,
                    response.usage.prompt_tokens, response.usage.completion_tokens,
                )

            results = parsed if isinstance(parsed, list) else parsed.get("results", [])
            normalized = []
            for r in results:
                normalized.append({
                    "pillar_scores": r.get("scores", {}),
                    "relevance_score": r.get("max_score", 1),
                    "summary": r.get("summary"),
                })

            while len(normalized) < len(batch):
                normalized.append({"pillar_scores": {}, "relevance_score": 1, "summary": None})

            log.info("BatchProcessor: scored %d research items in 1 call", len(batch))
            return normalized[:len(batch)]

        except Exception as exc:
            log.error("BatchProcessor: batch scoring failed: %s", exc)
            return [{"pillar_scores": {}, "relevance_score": 1, "summary": None} for _ in batch]
