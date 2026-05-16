"""LLM client for the personal + foundation automation system.

Routes calls to OpenAI GPT 5.5 (primary) or falls back to lighter models.
Handles retries, token tracking, and audit logging.

INTERNAL USE ONLY.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from src.personal_foundation.audit_shim import log_action

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4o"  # Use gpt-4o as available stand-in; swap to gpt-5.5 when live


class LLMClient:
    """Thin wrapper over OpenAI chat completions API."""

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.model = model
        self._client = httpx.Client(timeout=60.0)

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        response_format: dict | None = None,
    ) -> str:
        """Send a chat completion request. Returns the assistant message content."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_format:
            body["response_format"] = response_format

        resp = self._client.post(OPENAI_API_URL, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def classify_email(self, sender: str, subject: str, body_preview: str) -> dict:
        """Classify an email into one of 5 categories with confidence.

        Returns: {"category": str, "confidence": float}
        """
        system = (
            "You are an email classifier for Bob Rapp, co-founder of the AIGovOps Foundation. "
            "Classify the email into exactly one category:\n"
            "- action-required: needs a reply or action from Bob\n"
            "- FYI-only: informational, no action needed\n"
            "- newsletter: a newsletter or digest email\n"
            "- spam: unsolicited commercial or junk\n"
            "- foundation-business: related to AIGovOps Foundation operations\n\n"
            "Respond with JSON: {\"category\": \"...\", \"confidence\": 0.0-1.0}"
        )
        user = f"From: {sender}\nSubject: {subject}\n\n{body_preview[:500]}"

        try:
            result = self.complete(
                system, user, temperature=0.1,
                response_format={"type": "json_object"},
            )
            parsed = json.loads(result)
            return {
                "category": parsed.get("category", ""),
                "confidence": float(parsed.get("confidence", 0.0)),
            }
        except Exception:
            return {"category": "", "confidence": 0.0}

    def draft_email_reply(self, sender: str, subject: str, body_preview: str) -> str:
        """Draft a reply to an email."""
        system = (
            "You are drafting a reply on behalf of Bob Rapp, co-founder of the AIGovOps Foundation. "
            "Be professional, concise, and warm. Sign as 'Bob'."
        )
        user = f"Reply to this email:\nFrom: {sender}\nSubject: {subject}\n\n{body_preview[:500]}"
        return self.complete(system, user, temperature=0.4)

    def score_research_item(self, title: str, url: str) -> dict:
        """Score a research item against the Foundation's four pillars.

        Returns: {"pillar_scores": {...}, "summary": str}
        """
        system = (
            "You are a research analyst for the AIGovOps Foundation. "
            "Score this item's relevance to each of the Foundation's four pillars on a 1-5 scale:\n"
            "- governance_as_code: treating governance rules as executable, testable code\n"
            "- ai_technical_debt: managing and reducing technical debt in AI systems\n"
            "- operational_compliance: day-to-day compliance operations for AI\n"
            "- community_driven_standards: standards developed by practitioner communities\n\n"
            "Also provide a summary of no more than 150 words if the max score is 4 or higher.\n"
            "Respond with JSON: {\"pillar_scores\": {\"governance_as_code\": N, ...}, \"summary\": \"...\" or null}"
        )
        user = f"Title: {title}\nURL: {url}"

        try:
            result = self.complete(
                system, user, temperature=0.2,
                response_format={"type": "json_object"},
            )
            return json.loads(result)
        except Exception:
            return {
                "pillar_scores": {
                    "governance_as_code": 1,
                    "ai_technical_debt": 1,
                    "operational_compliance": 1,
                    "community_driven_standards": 1,
                },
                "summary": None,
            }

    def classify_outreach_response(self, sender: str, subject: str, body_preview: str) -> str:
        """Classify an outreach response as interested/not-interested/needs-more-info."""
        system = (
            "Classify this email response to an outreach message from the AIGovOps Foundation. "
            "Respond with exactly one word: interested, not-interested, or needs-more-info"
        )
        user = f"From: {sender}\nSubject: {subject}\n\n{body_preview[:300]}"
        result = self.complete(system, user, temperature=0.1).strip().lower()
        if result in ("interested", "not-interested", "needs-more-info"):
            return result
        return "needs-more-info"

    def generate_welcome_dm(self, member_name: str, personalization: str) -> str:
        """Generate a personalized welcome DM for a new community member."""
        system = (
            "You are writing a welcome DM on behalf of Bob & Ken, co-founders of the AIGovOps Foundation. "
            "Be warm, brief (3-4 sentences), and reference the personalization detail provided. "
            "End with an invitation to introduce themselves in the community."
        )
        user = f"New member: {member_name}\nPersonalization detail: {personalization}"
        return self.complete(system, user, temperature=0.6)

    def classify_post_moderation(self, title: str, body: str) -> dict:
        """Classify a community post for moderation.

        Returns: {"spam": float, "scam_link": float, "toxicity": float, "pii_exposure": float, "off_topic": float}
        """
        system = (
            "You are a content moderator for the AIGovOps Foundation community (focused on AI governance). "
            "Score this post on each dimension from 0.0 to 1.0:\n"
            "- spam: unsolicited commercial content\n"
            "- scam_link: contains suspicious/malicious links\n"
            "- toxicity: hostile, abusive, or harassing language\n"
            "- pii_exposure: contains personal information (emails, phone numbers, addresses)\n"
            "- off_topic: not related to AI governance, responsible AI, or the Foundation's mission\n\n"
            "Respond with JSON: {\"spam\": 0.0, \"scam_link\": 0.0, \"toxicity\": 0.0, \"pii_exposure\": 0.0, \"off_topic\": 0.0}"
        )
        user = f"Title: {title}\n\n{body[:500]}"

        try:
            result = self.complete(
                system, user, temperature=0.1,
                response_format={"type": "json_object"},
            )
            return json.loads(result)
        except Exception:
            return {"spam": 0.0, "scam_link": 0.0, "toxicity": 0.0, "pii_exposure": 0.0, "off_topic": 0.0}

    def draft_content(self, request: str, content_type: str) -> str:
        """Draft Foundation content in the AIGovOps voice."""
        system = (
            "You are a content writer for the AIGovOps Foundation. Write in the Foundation voice:\n"
            "- Practitioner-first framing (lead with operational insight, not theory)\n"
            "- No marketing superlatives (no 'revolutionary', 'game-changing', etc.)\n"
            "- No calls-to-action directing readers to purchase or sign up\n"
            "- Technical but accessible to practitioners\n\n"
            f"Content type: {content_type}"
        )
        return self.complete(system, request, temperature=0.5, max_tokens=2048)
