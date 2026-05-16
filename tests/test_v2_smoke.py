"""Smoke tests for v2 — verifies the full pipeline works without credentials.

Run: python3 -m pytest tests/test_v2_smoke.py -v
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestStateStore:
    """Verify SQLite state store operations."""

    def _store(self):
        from src.personal_foundation.v2.state import StateStore
        tmp = tempfile.mkdtemp()
        return StateStore(Path(tmp) / "test.db")

    def test_audit_log_append(self):
        store = self._store()
        seq = store.log_audit(agent="test/agent", action="test_action", status="success")
        assert seq >= 1
        entries = store.get_audit_log(limit=1)
        assert len(entries) == 1
        assert entries[0]["agent"] == "test/agent"

    def test_approval_queue_lifecycle(self):
        store = self._store()
        item_id = store.enqueue_approval(
            agent="test/agent", action_type="test",
            description="Test item", draft_content="Draft",
        )
        assert item_id
        pending = store.get_pending_approvals()
        assert len(pending) == 1
        assert pending[0]["id"] == item_id

        # Approve
        result = store.approve_item(item_id, "bob")
        assert result["status"] == "approved"
        assert result["reviewer"] == "bob"

        # No longer pending
        assert len(store.get_pending_approvals()) == 0

    def test_event_emit_and_retrieve(self):
        store = self._store()
        eid = store.emit_event("test.event", {"key": "value"})
        assert eid >= 1
        events = store.get_unprocessed_events("test.*")
        assert len(events) == 1
        store.mark_event_processed(eid, "test_consumer")
        assert len(store.get_unprocessed_events("test.*")) == 0

    def test_agent_suspend_resume(self):
        store = self._store()
        store.get_agent_state("test/agent")  # Initialize
        assert not store.is_agent_suspended("test/agent")
        store.suspend_agent("test/agent", "testing")
        assert store.is_agent_suspended("test/agent")
        store.resume_agent("test/agent")
        assert not store.is_agent_suspended("test/agent")


class TestPolicyEngine:
    """Verify policy evaluation."""

    def test_loads_policies(self):
        from src.personal_foundation.v2.policy import PolicyEngine
        engine = PolicyEngine()
        assert len(engine._rules) > 0

    def test_moderator_cannot_delete(self):
        from src.personal_foundation.v2.policy import PolicyEngine, PolicyContext
        engine = PolicyEngine()
        ctx = PolicyContext(
            principal="foundation/moderator",
            action="delete_post",
            resource_type="circle_post",
            resource_id="p1",
            attributes={},
        )
        decision = engine.evaluate(ctx)
        assert not decision.permitted

    def test_welcomer_can_dm(self):
        from src.personal_foundation.v2.policy import PolicyEngine, PolicyContext
        engine = PolicyEngine()
        ctx = PolicyContext(
            principal="foundation/welcomer",
            action="send_dm",
            resource_type="circle_member",
            resource_id="m1",
            attributes={"is_new_member": True},
        )
        decision = engine.evaluate(ctx)
        assert decision.permitted

    def test_bob_can_approve(self):
        from src.personal_foundation.v2.policy import PolicyEngine, PolicyContext
        engine = PolicyEngine()
        ctx = PolicyContext(
            principal="bob",
            action="approve",
            resource_type="approval_item",
            resource_id="item1",
            attributes={},
        )
        decision = engine.evaluate(ctx)
        assert decision.permitted


class TestEventBus:
    """Verify event bus subscription and dispatch."""

    def test_subscribe_and_emit(self):
        import asyncio
        from src.personal_foundation.v2.state import StateStore
        from src.personal_foundation.v2.event_bus import EventBus

        tmp = tempfile.mkdtemp()
        store = StateStore(Path(tmp) / "test.db")
        bus = EventBus(store)

        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe("test.*", "test_agent", handler)
        bus.emit("test.hello", {"msg": "world"})

        async def run():
            await bus._process_pending()

        asyncio.run(run())
        assert len(received) == 1
        assert received[0]["payload"]["msg"] == "world"


class TestScheduler:
    """Verify scheduler loads agent cron definitions."""

    def test_loads_schedules(self):
        pytest.importorskip("apscheduler")
        from src.personal_foundation.v2.state import StateStore
        from src.personal_foundation.v2.scheduler import Scheduler

        tmp = tempfile.mkdtemp()
        store = StateStore(Path(tmp) / "test.db")
        scheduler = Scheduler(store)
        count = scheduler.load_schedules()
        # Should find at least research_scanner (has cron)
        assert count >= 1
        assert "personal/research_scanner" in scheduler.jobs


class TestAgentYAMLs:
    """Verify all agent YAML files are valid."""

    def test_all_yamls_parse(self):
        import yaml
        agents_dir = Path("agents")
        assert agents_dir.exists()
        for f in agents_dir.glob("*.yaml"):
            with f.open() as fh:
                data = yaml.safe_load(fh)
            assert "agent" in data, f"{f.name} missing 'agent' key"
            assert "name" in data["agent"], f"{f.name} missing agent.name"
            assert "trigger" in data["agent"], f"{f.name} missing agent.trigger"
            assert "system_prompt" in data["agent"], f"{f.name} missing agent.system_prompt"

    def test_agent_names_prefixed(self):
        import yaml
        agents_dir = Path("agents")
        for f in agents_dir.glob("*.yaml"):
            with f.open() as fh:
                data = yaml.safe_load(fh)
            name = data["agent"]["name"]
            assert name.startswith("personal/") or name.startswith("foundation/"), \
                f"{f.name}: agent name '{name}' must start with personal/ or foundation/"


class TestDemoScript:
    """Verify the demo script runs without errors."""

    def test_demo_runs(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "scripts/demo.py"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"Demo failed:\n{result.stderr}"
        assert "Demo Complete" in result.stdout
        assert "OPERATIONAL" in result.stdout
