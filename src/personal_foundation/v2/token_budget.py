"""Token budget — daily spending caps per agent.

Prevents runaway costs. If an agent exceeds its daily budget, actions are
queued for tomorrow instead of executing immediately.

Default budgets:
- email_classifier: $0.50/day (high volume, cheap model)
- research_scanner: $1.00/day (daily scan)
- writing_agent: $2.00/day (expensive model, fewer calls)
- moderator: $0.50/day (high volume, cheap model)
- welcomer: $0.50/day (moderate volume)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.personal_foundation.v2.state import StateStore
from src.personal_foundation.v2.cost_tracker import CostTracker

log = logging.getLogger(__name__)

DEFAULT_BUDGETS = {
    "personal/email_classifier": 0.50,
    "personal/research_scanner": 1.00,
    "personal/task_agent": 0.50,
    "foundation/writing_agent": 2.00,
    "foundation/moderator": 0.50,
    "foundation/welcomer": 0.50,
    "foundation/curator": 0.50,
    "*": 5.00,  # Global daily cap
}


class TokenBudget:
    """Enforces daily spending caps per agent."""

    def __init__(self, store: StateStore, budgets: dict[str, float] | None = None) -> None:
        self.store = store
        self.budgets = budgets or DEFAULT_BUDGETS
        self.cost_tracker = CostTracker(store)

    def check_budget(self, agent: str) -> tuple[bool, float, float]:
        """Check if an agent is within its daily budget.

        Returns: (within_budget, spent_today, budget_limit)
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily = self.cost_tracker.get_daily_cost(today)

        spent = 0.0
        for a, data in daily.get("by_agent", {}).items():
            if a == agent:
                spent = data.get("cost", 0.0)
                break

        limit = self.budgets.get(agent, self.budgets.get("*", 5.0))
        within = spent < limit

        if not within:
            log.warning("TokenBudget: %s exceeded daily budget ($%.2f / $%.2f)", agent, spent, limit)
            self.store.log_audit(
                agent="system/token_budget", action="budget_exceeded",
                result_summary=f"{agent} exceeded daily budget: ${spent:.2f} / ${limit:.2f}",
            )

        return (within, spent, limit)

    def get_all_budgets(self) -> list[dict]:
        """Get budget status for all agents."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily = self.cost_tracker.get_daily_cost(today)

        results = []
        for agent, limit in self.budgets.items():
            if agent == "*":
                continue
            spent = daily.get("by_agent", {}).get(agent, {}).get("cost", 0.0)
            results.append({
                "agent": agent,
                "budget": limit,
                "spent": round(spent, 4),
                "remaining": round(max(0, limit - spent), 4),
                "pct_used": round(spent / max(limit, 0.01) * 100, 1),
            })
        return results

    def set_budget(self, agent: str, daily_limit: float) -> None:
        """Update an agent's daily budget."""
        self.budgets[agent] = daily_limit
        log.info("TokenBudget: set %s budget to $%.2f/day", agent, daily_limit)
