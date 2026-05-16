"""LLM client for the personal + foundation automation system.

Uses litellm for model routing and instructor for structured Pydantic output.
This eliminates JSON parsing bugs and enables automatic model fallback + cost tracking.

Model routing strategy:
- FAST (classification, scoring): groq/llama-3.1-70b-versatile (free/cheap, <1s)
- QUALITY (drafting, content): gpt-4o (best quality for writing)
- FALLBACK: gpt-4o-mini (if primary fails, still good, cheaper)

Cost comparison (per 1M tokens):
- Groq llama-3.1-70b: $0.59 input / $0.79 output (10x cheaper than GPT-4o)
- GPT-4o-mini: $0.15 input / $0.60 output
- GPT-4o: $2.50 input / $10.00 output

Strategy: Use Groq for all classification/scoring (80% of calls), GPT-4o only for
content that humans will read (drafts, newsletters, welcome DMs).

INTERNAL USE ONLY.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Optional

import instructor
from litellm import completion
from pydantic import BaseModel, Field

# Initialize instructor with litellm
client = instructor.from_litellm(completion)


# ---------------------------------------------------------------------------
# Model tiers
# ---------------------------------------------------------------------------

class ModelTier(str, Enum):
    """Model routing tiers based on task type."""
    FAST = "groq/llama-3.1-70b-versatile"   # Classification, scoring — cheap + fast
    QUALITY = "gpt-4o"                       # Drafting, content — best quality
    FALLBACK = "gpt-4o-mini"                 # Fallback if primary fails


# ---------------------------------------------------------------------------
# Structured output models (Pydantic — instructor guarantees these)
# ---------------------------------------------------------------------------

class EmailClassificationResult(BaseModel):
    """Structured email classification output."""
    category: str = Field(description="One of: action-required, FYI-only, newsletter, spam, foundation-business")
    confidence: float = Field(ge=0.0, le=1.0, description="Classification confidence 0.0-1.0")
    reasoning: str = Field(description="One-sentence explanation of why this category was chosen")


class ResearchScoreResult(BaseModel):
    """Structured research item scoring output."""
    governance_as_code: int = Field(ge=1, le=5)
    ai_technical_debt: int = Field(ge=1, le=5)
    operational_compliance: int = Field(ge=1, le=5)
    community_driven_standards: int = Field(ge=1, le=5)
    summary: Optional[str] = Field(default=None, description="150-word summary if max score >= 4, else null")


class OutreachResponseResult(BaseModel):
    """Structured outreach response classification."""
    classification: str = Field(description="One of: interested, not-interested, needs-more-info")
    reasoning: str = Field(description="One-sentence explanation")


class ModerationResult(BaseModel):
    """Structured content moderation scores."""
    spam: float = Field(ge=0.0, le=1.0)
    scam_link: float = Field(ge=0.0, le=1.0)
    toxicity: float = Field(ge=0.0, le=1.0)
    pii_exposure: float = Field(ge=0.0, le=1.0)
    off_topic: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# LLM functions — all use instructor for guaranteed structured output
# ---------------------------------------------------------------------------

def classify_email(sender: str, subject: str, body_preview: str) -> EmailClassificationResult:
    """Classify an email into one of 5 categories. Uses FAST tier (Groq)."""
    return client.chat.completions.create(
        model=ModelTier.FAST,
        response_model=EmailClassificationResult,
        messages=[
            {"role": "system", "content": (
                "You are an email classifier for Bob Rapp, co-founder of the AIGovOps Foundation. "
                "Classify into exactly one category:\n"
                "- action-required: needs a reply or action from Bob\n"
                "- FYI-only: informational, no action needed\n"
                "- newsletter: a newsletter or digest email\n"
                "- spam: unsolicited commercial or junk\n"
                "- foundation-business: related to AIGovOps Foundation operations"
            )},
            {"role": "user", "content": f"From: {sender}\nSubject: {subject}\n\n{body_preview[:500]}"},
        ],
        temperature=0.1,
    )


def draft_email_reply(sender: str, subject: str, body_preview: str) -> str:
    """Draft a reply to an email. Uses QUALITY tier (GPT-4o)."""
    resp = completion(
        model=ModelTier.QUALITY,
        messages=[
            {"role": "system", "content": (
                "You are drafting a reply on behalf of Bob Rapp, co-founder of the AIGovOps Foundation. "
                "Be professional, concise, and warm. Sign as 'Bob'. Keep under 150 words."
            )},
            {"role": "user", "content": f"Reply to:\nFrom: {sender}\nSubject: {subject}\n\n{body_preview[:500]}"},
        ],
        temperature=0.4,
        max_tokens=512,
    )
    return resp.choices[0].message.content


def score_research_item(title: str, url: str) -> ResearchScoreResult:
    """Score a research item against Foundation pillars. Uses FAST tier."""
    return client.chat.completions.create(
        model=ModelTier.FAST,
        response_model=ResearchScoreResult,
        messages=[
            {"role": "system", "content": (
                "Score this item's relevance to the AIGovOps Foundation's four pillars (1-5 each):\n"
                "- governance_as_code: treating governance rules as executable, testable code\n"
                "- ai_technical_debt: managing technical debt in AI systems\n"
                "- operational_compliance: day-to-day compliance operations for AI\n"
                "- community_driven_standards: standards developed by practitioner communities\n\n"
                "Provide a summary (max 150 words) ONLY if the highest score is 4 or 5. Otherwise set summary to null."
            )},
            {"role": "user", "content": f"Title: {title}\nURL: {url}"},
        ],
        temperature=0.2,
    )


def classify_outreach_response(sender: str, subject: str, body_preview: str) -> OutreachResponseResult:
    """Classify an outreach response. Uses FAST tier."""
    return client.chat.completions.create(
        model=ModelTier.FAST,
        response_model=OutreachResponseResult,
        messages=[
            {"role": "system", "content": (
                "Classify this email response to an outreach message from the AIGovOps Foundation. "
                "Determine if the person is interested, not-interested, or needs-more-info."
            )},
            {"role": "user", "content": f"From: {sender}\nSubject: {subject}\n\n{body_preview[:300]}"},
        ],
        temperature=0.1,
    )


def generate_welcome_dm(member_name: str, personalization: str) -> str:
    """Generate a personalized welcome DM. Uses QUALITY tier."""
    resp = completion(
        model=ModelTier.QUALITY,
        messages=[
            {"role": "system", "content": (
                "Write a welcome DM on behalf of Bob & Ken, co-founders of the AIGovOps Foundation. "
                "Be warm, brief (3-4 sentences), reference the personalization detail. "
                "End with an invitation to introduce themselves. No emojis overload."
            )},
            {"role": "user", "content": f"New member: {member_name}\nPersonalization: {personalization}"},
        ],
        temperature=0.6,
        max_tokens=256,
    )
    return resp.choices[0].message.content


def classify_post_moderation(title: str, body: str) -> ModerationResult:
    """Classify a community post for moderation. Uses FAST tier."""
    return client.chat.completions.create(
        model=ModelTier.FAST,
        response_model=ModerationResult,
        messages=[
            {"role": "system", "content": (
                "You are a content moderator for the AIGovOps Foundation community (AI governance focus). "
                "Score this post on each dimension from 0.0 to 1.0:\n"
                "- spam: unsolicited commercial content\n"
                "- scam_link: suspicious/malicious links\n"
                "- toxicity: hostile, abusive language\n"
                "- pii_exposure: personal info (emails, phones, addresses)\n"
                "- off_topic: not related to AI governance"
            )},
            {"role": "user", "content": f"Title: {title}\n\n{body[:500]}"},
        ],
        temperature=0.1,
    )


def draft_content(request: str, content_type: str) -> str:
    """Draft Foundation content. Uses QUALITY tier."""
    resp = completion(
        model=ModelTier.QUALITY,
        messages=[
            {"role": "system", "content": (
                "You are a content writer for the AIGovOps Foundation. Write in the Foundation voice:\n"
                "- Practitioner-first framing (lead with operational insight, not theory)\n"
                "- No marketing superlatives (no 'revolutionary', 'game-changing', etc.)\n"
                "- No calls-to-action directing readers to purchase or sign up\n"
                "- Technical but accessible to practitioners\n\n"
                f"Content type: {content_type}"
            )},
            {"role": "user", "content": request},
        ],
        temperature=0.5,
        max_tokens=2048,
    )
    return resp.choices[0].message.content


def draft_linkedin_variant(request: str, min_words: int, max_words: int) -> str:
    """Draft a LinkedIn post variant within word bounds. Uses QUALITY tier."""
    resp = completion(
        model=ModelTier.QUALITY,
        messages=[
            {"role": "system", "content": (
                "Write a LinkedIn post for the AIGovOps Foundation. Foundation voice:\n"
                "- Practitioner-first, no superlatives, no CTAs\n"
                f"- STRICT word count: {min_words}-{max_words} words. Count carefully."
            )},
            {"role": "user", "content": request},
        ],
        temperature=0.6,
        max_tokens=1024,
    )
    return resp.choices[0].message.content


def draft_outreach_message(contact_name: str, context: str, message_type: str = "first_contact") -> str:
    """Draft an outreach message. Uses QUALITY tier."""
    if message_type == "first_contact":
        system = (
            "Write a first-contact outreach message from the AIGovOps Foundation. "
            "Introduce the Foundation briefly, express interest in collaboration, "
            "suggest a short call. Under 150 words. Warm and professional."
        )
    else:
        system = (
            "Write a follow-up message from the AIGovOps Foundation. "
            "Reference prior contact, be brief (under 100 words), warm, not pushy."
        )

    resp = completion(
        model=ModelTier.QUALITY,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"Contact: {contact_name}\nContext: {context}"},
        ],
        temperature=0.5,
        max_tokens=512,
    )
    return resp.choices[0].message.content
