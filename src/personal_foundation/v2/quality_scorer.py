"""Quality Scorecard — 5-dimension scoring for AI artifacts.

Dimensions:
1. Accuracy — are claims verifiable?
2. Voice — does it match the org's tone?
3. Safety — no PII, secrets, bias, harm?
4. Freshness — is referenced info current?
5. Authority — is the approval chain complete?

Artifacts below threshold (default 70% on any dimension) are held for review.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 0.70


@dataclass
class QualityScore:
    """Score for a single dimension (0.0 to 1.0)."""
    dimension: str
    score: float
    details: str = ""

    @property
    def passes(self) -> bool:
        return self.score >= DEFAULT_THRESHOLD

    @property
    def display(self) -> str:
        bar_len = int(self.score * 10)
        bar = "█" * bar_len + "░" * (10 - bar_len)
        status = "✅" if self.passes else "⚠️"
        return f"{status} {self.dimension}: {bar} {self.score:.0%}"


@dataclass
class Scorecard:
    """Complete quality scorecard for an artifact."""
    artifact_id: str
    scores: list[QualityScore]
    threshold: float = DEFAULT_THRESHOLD

    @property
    def overall_pass(self) -> bool:
        return all(s.score >= self.threshold for s in self.scores)

    @property
    def min_score(self) -> float:
        return min(s.score for s in self.scores) if self.scores else 0.0

    @property
    def avg_score(self) -> float:
        return sum(s.score for s in self.scores) / len(self.scores) if self.scores else 0.0

    @property
    def failing_dimensions(self) -> list[str]:
        return [s.dimension for s in self.scores if s.score < self.threshold]

    def display(self) -> str:
        lines = [f"📊 Quality Scorecard — {'PASS ✅' if self.overall_pass else 'REVIEW ⚠️'}\n"]
        for s in self.scores:
            lines.append(f"  {s.display}")
        lines.append(f"\n  Overall: {self.avg_score:.0%} (threshold: {self.threshold:.0%})")
        if not self.overall_pass:
            lines.append(f"  ⚠️ Failing: {', '.join(self.failing_dimensions)}")
        return "\n".join(lines)


class QualityScorer:
    """Scores artifacts on 5 quality dimensions."""

    def __init__(self, threshold: float = DEFAULT_THRESHOLD) -> None:
        self.threshold = threshold

    def score(self, artifact_id: str, content: str, context: dict = None) -> Scorecard:
        """Score an artifact on all 5 dimensions.

        Args:
            artifact_id: Unique artifact identifier
            content: The artifact text content
            context: Additional context (agent, action_type, org voice rules, etc.)

        Returns:
            Scorecard with all dimension scores
        """
        ctx = context or {}

        scores = [
            self._score_accuracy(content, ctx),
            self._score_voice(content, ctx),
            self._score_safety(content),
            self._score_freshness(content, ctx),
            self._score_authority(ctx),
        ]

        return Scorecard(artifact_id=artifact_id, scores=scores, threshold=self.threshold)

    def _score_accuracy(self, content: str, ctx: dict) -> QualityScore:
        """Dimension 1: Are claims verifiable?

        Checks for:
        - Specific numbers/stats (should have sources)
        - Named entities (should be real)
        - Dates (should be plausible)
        """
        issues = []

        # Check for unsourced statistics
        stat_patterns = re.findall(r'\d+%|\$[\d,]+|\d+ (?:million|billion|thousand)', content)
        if stat_patterns and "source" not in content.lower() and "according" not in content.lower():
            issues.append("Contains statistics without attribution")

        # Check for future dates presented as fact
        import datetime
        year_mentions = re.findall(r'20\d{2}', content)
        current_year = datetime.datetime.now().year
        future_claims = [y for y in year_mentions if int(y) > current_year + 1]
        if future_claims:
            issues.append(f"References future dates as fact: {future_claims}")

        score = 1.0 - (len(issues) * 0.15)
        return QualityScore("Accuracy", max(0.0, min(1.0, score)), "; ".join(issues) or "No issues")

    def _score_voice(self, content: str, ctx: dict) -> QualityScore:
        """Dimension 2: Does it match the org's tone?

        Default rules (AIGovOps Foundation):
        - Practitioner-first (not academic)
        - No marketing superlatives
        - No CTAs
        """
        issues = []
        content_lower = content.lower()

        # Superlatives
        superlatives = ["revolutionary", "game-changing", "groundbreaking", "unprecedented",
                       "best-in-class", "world-class", "cutting-edge", "disruptive"]
        found_superlatives = [s for s in superlatives if s in content_lower]
        if found_superlatives:
            issues.append(f"Superlatives: {', '.join(found_superlatives)}")

        # CTAs
        cta_patterns = ["sign up", "subscribe now", "buy now", "click here", "learn more", "join now"]
        found_ctas = [c for c in cta_patterns if c in content_lower]
        if found_ctas:
            issues.append(f"CTAs: {', '.join(found_ctas)}")

        # Too academic (passive voice overuse)
        passive_indicators = content_lower.count(" is ") + content_lower.count(" was ") + content_lower.count(" been ")
        words = len(content.split())
        if words > 50 and passive_indicators / max(words, 1) > 0.05:
            issues.append("High passive voice usage (may be too academic)")

        score = 1.0 - (len(issues) * 0.2)
        return QualityScore("Voice", max(0.0, min(1.0, score)), "; ".join(issues) or "Matches voice")

    def _score_safety(self, content: str) -> QualityScore:
        """Dimension 3: No PII, secrets, bias, harm."""
        issues = []

        # PII patterns
        if re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', content):
            issues.append("Contains email address")
        if re.search(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', content):
            issues.append("Contains phone number")
        if re.search(r'\b(?:sk-|gsk_|pplx-|Bearer\s)[A-Za-z0-9_-]{20,}\b', content):
            issues.append("Contains API key")

        # Bias indicators (simplified)
        bias_terms = ["all women", "all men", "always", "never", "every single"]
        found_bias = [b for b in bias_terms if b in content.lower()]
        if found_bias:
            issues.append(f"Potential bias: absolute language ({', '.join(found_bias)})")

        score = 1.0 - (len(issues) * 0.3)
        return QualityScore("Safety", max(0.0, min(1.0, score)), "; ".join(issues) or "Safe")

    def _score_freshness(self, content: str, ctx: dict) -> QualityScore:
        """Dimension 4: Is referenced information current?"""
        issues = []

        # Check for old year references
        import datetime
        current_year = datetime.datetime.now().year
        old_years = re.findall(r'20[12]\d', content)
        old_refs = [y for y in old_years if int(y) < current_year - 2]
        if old_refs:
            issues.append(f"References from {min(old_refs)}-{max(old_refs)} (may be outdated)")

        # Check for "recently" without specifics
        if "recently" in content.lower() and not re.search(r'(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+20\d{2}', content):
            issues.append("Uses 'recently' without specific date")

        score = 1.0 - (len(issues) * 0.15)
        return QualityScore("Freshness", max(0.0, min(1.0, score)), "; ".join(issues) or "Current")

    def _score_authority(self, ctx: dict) -> QualityScore:
        """Dimension 5: Is the approval chain complete?"""
        # Check if there's an approval record
        has_approval = ctx.get("approved", False) or ctx.get("auto_approved", False)
        has_operator = bool(ctx.get("operator"))
        has_policy = bool(ctx.get("policy_result"))

        score = 0.0
        details = []

        if has_approval:
            score += 0.4
            details.append("Approved")
        else:
            details.append("Not yet approved")

        if has_operator:
            score += 0.3
            details.append(f"Operator: {ctx.get('operator')}")
        else:
            details.append("No operator recorded")

        if has_policy:
            score += 0.3
            details.append("Policy evaluated")
        else:
            details.append("No policy evaluation")

        return QualityScore("Authority", min(1.0, score), "; ".join(details))
