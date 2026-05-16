"""Confidence-gated auto-approve — skips the queue for high-confidence safe actions.

Rules:
- Email classified as spam with confidence > 95% → auto-archive (no queue)
- Email classified as FYI-only with confidence > 95% → auto-archive (no queue)
- Email classified as newsletter with confidence > 95% → auto-archive + extract (no queue)
- Welcome DMs → always auto-approved (policy pre-approves)
- Research digest delivery → always auto-approved (informational only)

Everything else still goes through the Approval Queue.

This reduces Bob's daily approvals from ~30 to ~5 (only action-required emails,
content drafts, and moderation flags need human review).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.personal_foundation.v2.state import StateStore

log = logging.getLogger(__name__)

# Auto-approve rules: (agent_pattern, action_type, min_confidence)
AUTO_APPROVE_RULES = [
    # Email classifications that never need review
    {"agent": "personal/email_classifier", "category": "spam", "min_confidence": 0.95},
    {"agent": "personal/email_classifier", "category": "FYI-only", "min_confidence": 0.95},
    {"agent": "personal/email_classifier", "category": "newsletter", "min_confidence": 0.95},

    # Agents that are pre-approved by policy
    {"agent": "foundation/welcomer", "action_type": "*", "min_confidence": 0.0},
    {"agent": "personal/research_scanner", "action_type": "digest_delivery", "min_confidence": 0.0},

    # Task reminders (informational, no external action)
    {"agent": "personal/task_agent", "action_type": "stale_reminder", "min_confidence": 0.0},
    {"agent": "personal/task_agent", "action_type": "milestone_alert", "min_confidence": 0.0},
]

# Actions that ALWAYS require human approval (never auto-approve)
ALWAYS_REQUIRE_APPROVAL = [
    "email_draft",          # Sending emails on Bob's behalf
    "content_draft",        # Publishing content
    "newsletter_draft",     # Newsletter distribution
    "outreach_first_contact",  # First contact with new people
    "outreach_followup",    # Follow-up messages
    "redirect_comment",     # Moderator redirect comments
    "weekly_status_report", # Reports before distribution
]


@dataclass
class AutoApproveDecision:
    """Result of auto-approve evaluation."""
    auto_approved: bool
    reason: str
    rule_matched: str = ""


class AutoApprover:
    """Evaluates whether an action can be auto-approved."""

    def __init__(self, store: StateStore) -> None:
        self.store = store
        self._custom_rules: list[dict] = []  # Learned rules from Bob's behavior
        self._auto_approved_count = 0
        self._queued_count = 0

    def evaluate(self, agent: str, action_type: str, confidence: float = 1.0, category: str = "") -> AutoApproveDecision:
        """Decide if an action can be auto-approved.

        Returns AutoApproveDecision with the verdict and reason.
        """
        # ALWAYS require approval for these action types
        if action_type in ALWAYS_REQUIRE_APPROVAL:
            self._queued_count += 1
            return AutoApproveDecision(
                auto_approved=False,
                reason=f"Action type '{action_type}' always requires human approval",
            )

        # Check built-in rules
        for rule in AUTO_APPROVE_RULES:
            if self._rule_matches(rule, agent, action_type, confidence, category):
                self._auto_approved_count += 1
                self.store.log_audit(
                    agent="system/auto_approve", action="auto_approved",
                    result_summary=f"Auto-approved: {agent}:{action_type} (conf={confidence:.2f})",
                    details={"agent": agent, "action_type": action_type, "confidence": confidence},
                )
                return AutoApproveDecision(
                    auto_approved=True,
                    reason=f"Matched rule: {rule}",
                    rule_matched=str(rule),
                )

        # Check learned rules (from Bob's behavior)
        for rule in self._custom_rules:
            if self._rule_matches(rule, agent, action_type, confidence, category):
                self._auto_approved_count += 1
                return AutoApproveDecision(
                    auto_approved=True,
                    reason=f"Learned rule: {rule.get('description', 'custom')}",
                    rule_matched=str(rule),
                )

        # Default: require approval
        self._queued_count += 1
        return AutoApproveDecision(
            auto_approved=False,
            reason="No auto-approve rule matched; requires human review",
        )

    def add_learned_rule(self, agent: str, action_type: str, min_confidence: float, description: str) -> None:
        """Add a learned auto-approve rule (from Bob's behavior patterns)."""
        self._custom_rules.append({
            "agent": agent,
            "action_type": action_type,
            "min_confidence": min_confidence,
            "description": description,
        })
        log.info("AutoApprover: learned new rule: %s", description)

    @property
    def stats(self) -> dict:
        """Return auto-approve statistics."""
        total = self._auto_approved_count + self._queued_count
        rate = self._auto_approved_count / max(total, 1)
        return {
            "auto_approved": self._auto_approved_count,
            "queued_for_review": self._queued_count,
            "auto_approve_rate": round(rate, 3),
            "custom_rules": len(self._custom_rules),
        }

    def _rule_matches(self, rule: dict, agent: str, action_type: str, confidence: float, category: str) -> bool:
        """Check if a rule matches the given action."""
        # Agent match
        rule_agent = rule.get("agent", "*")
        if rule_agent != "*" and rule_agent != agent:
            if not (rule_agent.endswith("*") and agent.startswith(rule_agent[:-1])):
                return False

        # Action type match
        rule_action = rule.get("action_type", "*")
        if rule_action != "*" and rule_action != action_type:
            return False

        # Category match (for email classifier)
        rule_category = rule.get("category", "")
        if rule_category and rule_category != category:
            return False

        # Confidence threshold
        min_conf = rule.get("min_confidence", 0.0)
        if confidence < min_conf:
            return False

        return True
