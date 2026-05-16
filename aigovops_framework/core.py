"""Framework — the main entry point for the AIGovOps Agent Framework.

Usage:
    from aigovops_framework import Framework

    fw = Framework(db_path="data/my_app.db", dry_run=False)
    fw.load_agents("agents/")
    fw.load_policies("policies/")
    fw.start()  # Blocks, runs event loop + API server
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from aigovops_framework.state import StateStore
from aigovops_framework.events import EventBus
from aigovops_framework.policy import PolicyEngine
from aigovops_framework.engine import AgentEngine
from aigovops_framework.cache import LLMCache
from aigovops_framework.costs import CostTracker
from aigovops_framework.feedback import FeedbackStore

log = logging.getLogger(__name__)


class Framework:
    """The AIGovOps Agent Framework — one object to rule them all.

    Provides:
    - State persistence (SQLite)
    - Event bus (pub/sub)
    - Policy engine (permit/deny)
    - Agent runtime (YAML-driven)
    - LLM caching
    - Cost tracking
    - Feedback loops
    - Approval queue
    """

    def __init__(
        self,
        db_path: str | Path = "data/framework.db",
        dry_run: bool = False,
        api_port: int = 8000,
    ) -> None:
        self.dry_run = dry_run
        self.api_port = api_port

        # Core components
        self.store = StateStore(Path(db_path))
        self.event_bus = EventBus(self.store)
        self.policy = PolicyEngine()
        self.engine = AgentEngine(
            store=self.store,
            event_bus=self.event_bus,
            policy_engine=self.policy,
            dry_run=dry_run,
        )

        # Intelligence layer
        self.cache = LLMCache(self.store)
        self.costs = CostTracker(self.store)
        self.feedback = FeedbackStore(self.store)

        self._agents_loaded = 0
        self._policies_loaded = 0

    def load_agents(self, agents_dir: str | Path = "agents/") -> int:
        """Load agent YAML definitions from a directory.

        Returns the number of agents loaded.
        """
        self._agents_loaded = self.engine.load_agents(Path(agents_dir))
        log.info("Framework: %d agents loaded from %s", self._agents_loaded, agents_dir)
        return self._agents_loaded

    def load_policies(self, policies_dir: str | Path = "policies/") -> int:
        """Load policy YAML files from a directory.

        Returns the number of rules loaded.
        """
        self.policy.policies_dir = Path(policies_dir)
        self.policy.reload()
        self._policies_loaded = len(self.policy._rules)
        log.info("Framework: %d policy rules loaded from %s", self._policies_loaded, policies_dir)
        return self._policies_loaded

    def emit(self, event_type: str, payload: dict = None) -> int:
        """Emit an event into the event bus. Returns event ID."""
        return self.event_bus.emit(event_type, payload or {})

    def enqueue(self, agent: str, action_type: str, description: str, draft: str, rationale: str = "") -> str:
        """Create an approval queue item. Returns item ID."""
        return self.store.enqueue_approval(
            agent=agent, action_type=action_type,
            description=description, draft_content=draft, rationale=rationale,
        )

    def approve(self, item_id: str, reviewer: str) -> dict:
        """Approve an approval queue item."""
        result = self.store.approve_item(item_id, reviewer)
        self.store.log_audit(
            agent="system/framework", action="approve",
            operator=reviewer, result_summary=f"Approved {item_id}",
        )
        return result

    def reject(self, item_id: str, reviewer: str, reason: str = "") -> dict:
        """Reject an approval queue item."""
        result = self.store.reject_item(item_id, reviewer, reason)
        self.store.log_audit(
            agent="system/framework", action="reject",
            operator=reviewer, result_summary=f"Rejected {item_id}: {reason[:50]}",
        )
        return result

    def suspend(self, agent_name: str, reason: str = "") -> None:
        """Suspend an agent."""
        self.store.suspend_agent(agent_name, reason)
        self.store.log_audit(
            agent="system/framework", action="suspend",
            result_summary=f"Suspended {agent_name}: {reason}",
        )

    def resume(self, agent_name: str) -> None:
        """Resume a suspended agent."""
        self.store.resume_agent(agent_name)
        self.store.log_audit(
            agent="system/framework", action="resume",
            result_summary=f"Resumed {agent_name}",
        )

    def start(self) -> None:
        """Start the framework (blocking). Runs event loop + optional API server."""
        self.store.log_audit(
            agent="system/framework", action="startup",
            result_summary=f"Framework started: {self._agents_loaded} agents, {self._policies_loaded} rules, dry_run={self.dry_run}",
        )

        log.info("=" * 50)
        log.info("AIGovOps Agent Framework v%s", "0.1.0")
        log.info("  Agents: %d", self._agents_loaded)
        log.info("  Policies: %d rules", self._policies_loaded)
        log.info("  Dry-run: %s", self.dry_run)
        log.info("  Database: %s", self.store.db_path)
        log.info("=" * 50)

        asyncio.run(self._run())

    async def _run(self) -> None:
        """Internal async run loop."""
        try:
            await self.event_bus.start()
        except (KeyboardInterrupt, asyncio.CancelledError):
            self.event_bus.stop()
            self.store.log_audit(
                agent="system/framework", action="shutdown",
                result_summary="Clean shutdown",
            )

    @property
    def status(self) -> dict:
        """Get framework status summary."""
        pending = self.store.get_pending_approvals()
        return {
            "agents_loaded": self._agents_loaded,
            "policies_loaded": self._policies_loaded,
            "pending_approvals": len(pending),
            "dry_run": self.dry_run,
            "cache_stats": self.cache.stats,
            "cost_report": self.costs.get_daily_cost(),
        }
