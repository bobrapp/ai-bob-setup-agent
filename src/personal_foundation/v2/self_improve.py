"""Self-improvement report — weekly analysis of agent performance.

Analyzes Bob's edit patterns and suggests improvements:
- "You edited 80% of LinkedIn drafts to be shorter → should I default shorter?"
- "Email classifier accuracy is 92% → consider auto-approving at 90%+"
- "Research scanner found 0 items 3 days this week → broaden search terms?"
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from src.personal_foundation.v2.state import StateStore
from src.personal_foundation.v2.feedback import FeedbackStore
from src.personal_foundation.v2.cost_tracker import CostTracker

log = logging.getLogger(__name__)


class SelfImproveReport:
    """Generates weekly self-improvement suggestions."""

    def __init__(self, store: StateStore) -> None:
        self.store = store
        self.feedback = FeedbackStore(store)
        self.costs = CostTracker(store)

    def generate(self) -> str:
        """Generate the weekly self-improvement report."""
        sections = ["# 🧠 Weekly Self-Improvement Report\n"]

        # Feedback patterns
        fb_section = self._analyze_feedback()
        if fb_section:
            sections.append(fb_section)

        # Approval patterns
        approval_section = self._analyze_approvals()
        if approval_section:
            sections.append(approval_section)

        # Cost optimization
        cost_section = self._analyze_costs()
        if cost_section:
            sections.append(cost_section)

        # Agent health
        health_section = self._analyze_health()
        if health_section:
            sections.append(health_section)

        if len(sections) == 1:
            sections.append("No suggestions this week — everything looks good! ✅")

        return "\n".join(sections)

    def _analyze_feedback(self) -> str:
        """Analyze edit patterns from feedback store."""
        stats = self.feedback.get_stats()
        if stats["total_feedback"] == 0:
            return ""

        lines = ["## ✏️ Edit Patterns\n"]
        for agent, count in stats.get("by_agent", {}).items():
            if count >= 3:
                lines.append(f"- **{agent}**: {count} edits this period")
                lines.append(f"  → Suggestion: Review this agent's prompts or add few-shot examples")
        return "\n".join(lines) if len(lines) > 1 else ""

    def _analyze_approvals(self) -> str:
        """Analyze approval patterns — suggest auto-approve promotions."""
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        entries = self.store.get_audit_log(limit=500)

        # Count approvals without edits per agent
        approve_counts: dict[str, int] = {}
        for e in entries:
            if e.get("action") == "approve" and e.get("timestamp", "") > week_ago:
                agent = e.get("details_json", "")
                if "agent" in str(agent):
                    approve_counts[e.get("agent", "")] = approve_counts.get(e.get("agent", ""), 0) + 1

        lines = ["## ✅ Auto-Approve Candidates\n"]
        for agent, count in sorted(approve_counts.items(), key=lambda x: -x[1]):
            if count >= 5:
                lines.append(f"- **{agent}**: approved {count} times without edit")
                lines.append(f"  → Consider adding to auto-approve rules")

        return "\n".join(lines) if len(lines) > 1 else ""

    def _analyze_costs(self) -> str:
        """Suggest cost optimizations."""
        report = self.costs.get_weekly_report()
        if report["total_calls"] == 0:
            return ""

        lines = ["## 💰 Cost Optimization\n"]
        lines.append(f"- Total cost this week: ${report['total_cost']:.2f}")
        lines.append(f"- Cache savings: {report['cache_savings_pct']}% of calls cached")

        if report["cache_savings_pct"] < 20:
            lines.append(f"  → Suggestion: Cache hit rate is low. Consider longer TTL or semantic caching.")

        # Find expensive agents
        for item in report.get("by_agent", []):
            if item["cost"] > report["total_cost"] * 0.4:
                lines.append(f"- **{item['agent']}** uses {item['cost']:.2f} ({int(item['cost']/max(report['total_cost'],0.01)*100)}% of total)")
                lines.append(f"  → Consider using a cheaper model for this agent")

        return "\n".join(lines)

    def _analyze_health(self) -> str:
        """Check agent health patterns."""
        entries = self.store.get_audit_log(limit=200, status="failure")
        if not entries:
            return ""

        failure_agents: dict[str, int] = {}
        for e in entries:
            agent = e.get("agent", "")
            failure_agents[agent] = failure_agents.get(agent, 0) + 1

        lines = ["## ⚠️ Health Concerns\n"]
        for agent, count in sorted(failure_agents.items(), key=lambda x: -x[1]):
            if count >= 3:
                lines.append(f"- **{agent}**: {count} failures this week")
                lines.append(f"  → Investigate error patterns in audit log")

        return "\n".join(lines) if len(lines) > 1 else ""
