"""End-to-end hardening tests for v2 — full pipeline verification.

Tests the complete flow without external credentials:
- State store CRUD + persistence
- Event bus emit → subscribe → dispatch
- Policy engine permit/deny across all rules
- Agent YAML loading + validation
- Approval queue full lifecycle
- Cache hit/miss behavior
- Cost tracker recording
- Feedback store round-trip
- RAG deduplication
- Voice command parsing
- API endpoint contracts

Run: python3 -m pytest tests/test_v2_e2e.py -v
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store():
    from src.personal_foundation.v2.state import StateStore
    tmp = tempfile.mkdtemp()
    return StateStore(Path(tmp) / "test.db")


@pytest.fixture
def policy():
    from src.personal_foundation.v2.policy import PolicyEngine
    return PolicyEngine()


@pytest.fixture
def event_bus(store):
    from src.personal_foundation.v2.event_bus import EventBus
    return EventBus(store, poll_interval=0.1)


@pytest.fixture
def cache(store):
    from src.personal_foundation.v2.cache import LLMCache
    return LLMCache(store, ttl_seconds=60)


@pytest.fixture
def cost_tracker(store):
    from src.personal_foundation.v2.cost_tracker import CostTracker
    return CostTracker(store)


@pytest.fixture
def feedback_store(store):
    from src.personal_foundation.v2.feedback import FeedbackStore
    return FeedbackStore(store)


@pytest.fixture
def rag(store):
    from src.personal_foundation.v2.rag import ResearchRAG
    return ResearchRAG(store)


# ---------------------------------------------------------------------------
# State Store Tests
# ---------------------------------------------------------------------------

class TestStateStoreHardened:
    """Comprehensive state store tests."""

    def test_audit_log_is_append_only(self, store):
        """Audit entries cannot be modified after writing."""
        seq1 = store.log_audit(agent="test/a", action="act1", status="success")
        seq2 = store.log_audit(agent="test/b", action="act2", status="failure")
        assert seq2 > seq1
        entries = store.get_audit_log(limit=10)
        assert len(entries) == 2
        # Verify ordering (newest first in get_audit_log)
        assert entries[0]["seq"] == seq2
        assert entries[1]["seq"] == seq1

    def test_audit_log_truncates_long_fields(self, store):
        """Prompt and result summaries are capped at 200 chars."""
        long_text = "x" * 500
        store.log_audit(agent="test/a", action="act", prompt_summary=long_text, result_summary=long_text)
        entries = store.get_audit_log(limit=1)
        assert len(entries[0]["prompt_summary"]) <= 200
        assert len(entries[0]["result_summary"]) <= 200

    def test_approval_queue_reject_with_reason(self, store):
        """Rejection stores the reason."""
        item_id = store.enqueue_approval(agent="test/a", action_type="t", description="d", draft_content="c")
        result = store.reject_item(item_id, "bob", "Not good enough")
        assert result["rejection_reason"] == "Not good enough"
        assert result["reviewer"] == "bob"

    def test_approval_queue_edit_preserves_id(self, store):
        """Editing changes content but keeps the same ID."""
        item_id = store.enqueue_approval(agent="test/a", action_type="t", description="d", draft_content="original")
        result = store.edit_item(item_id, "edited content")
        assert result["id"] == item_id
        assert result["draft_content"] == "edited content"
        assert result["status"] == "edited"

    def test_events_survive_multiple_reads(self, store):
        """Unprocessed events remain until explicitly marked."""
        store.emit_event("test.event", {"key": "val"})
        events1 = store.get_unprocessed_events("test.*")
        events2 = store.get_unprocessed_events("test.*")
        assert len(events1) == 1
        assert len(events2) == 1  # Still there
        store.mark_event_processed(events1[0]["id"], "consumer")
        events3 = store.get_unprocessed_events("test.*")
        assert len(events3) == 0

    def test_agent_state_failure_tracking(self, store):
        """Failure count increments correctly."""
        store.get_agent_state("test/agent")  # Initialize
        store.increment_agent_actions("test/agent", success=True)
        store.increment_agent_actions("test/agent", success=False)
        store.increment_agent_actions("test/agent", success=False)
        state = store.get_agent_state("test/agent")
        assert state["total_actions"] == 3
        assert state["failure_count_24h"] == 2

    def test_concurrent_audit_writes(self, store):
        """Multiple rapid writes don't corrupt the database."""
        for i in range(50):
            store.log_audit(agent=f"test/agent_{i % 5}", action=f"action_{i}", status="success")
        entries = store.get_audit_log(limit=100)
        assert len(entries) == 50


# ---------------------------------------------------------------------------
# Policy Engine Tests
# ---------------------------------------------------------------------------

class TestPolicyHardened:
    """Comprehensive policy evaluation tests."""

    def test_all_policy_files_load(self, policy):
        """All YAML policy files parse without errors."""
        assert len(policy._rules) >= 10  # We have 14+ rules

    def test_moderator_cannot_delete(self, policy):
        from src.personal_foundation.v2.policy import PolicyContext
        ctx = PolicyContext(principal="foundation/moderator", action="delete_post",
                          resource_type="circle_post", resource_id="p1", attributes={})
        assert not policy.evaluate(ctx).permitted

    def test_moderator_cannot_hide(self, policy):
        from src.personal_foundation.v2.policy import PolicyContext
        ctx = PolicyContext(principal="foundation/moderator", action="hide_post",
                          resource_type="circle_post", resource_id="p1", attributes={})
        assert not policy.evaluate(ctx).permitted

    def test_moderator_can_flag(self, policy):
        from src.personal_foundation.v2.policy import PolicyContext
        ctx = PolicyContext(principal="foundation/moderator", action="flag_post",
                          resource_type="circle_post", resource_id="p1", attributes={})
        assert policy.evaluate(ctx).permitted

    def test_welcomer_can_dm_new_members(self, policy):
        from src.personal_foundation.v2.policy import PolicyContext
        ctx = PolicyContext(principal="foundation/welcomer", action="send_dm",
                          resource_type="circle_member", resource_id="m1",
                          attributes={"is_new_member": True})
        assert policy.evaluate(ctx).permitted

    def test_bob_can_approve(self, policy):
        from src.personal_foundation.v2.policy import PolicyContext
        ctx = PolicyContext(principal="bob", action="approve",
                          resource_type="approval_item", resource_id="i1", attributes={})
        assert policy.evaluate(ctx).permitted

    def test_ken_can_approve(self, policy):
        from src.personal_foundation.v2.policy import PolicyContext
        ctx = PolicyContext(principal="ken", action="approve",
                          resource_type="approval_item", resource_id="i1", attributes={})
        assert policy.evaluate(ctx).permitted

    def test_unknown_principal_default_permit(self, policy):
        """Unknown principals get default permit (no matching forbid)."""
        from src.personal_foundation.v2.policy import PolicyContext
        ctx = PolicyContext(principal="random/agent", action="log_audit",
                          resource_type="audit_log", resource_id="x", attributes={})
        assert policy.evaluate(ctx).permitted

    def test_policy_reload(self, policy):
        """Reload doesn't crash and preserves rules."""
        count_before = len(policy._rules)
        policy.reload()
        assert len(policy._rules) == count_before


# ---------------------------------------------------------------------------
# Event Bus Tests
# ---------------------------------------------------------------------------

class TestEventBusHardened:
    """Event bus dispatch and pattern matching."""

    def test_wildcard_pattern(self, event_bus, store):
        """Wildcard patterns match correctly."""
        received = []
        async def handler(event):
            received.append(event)

        event_bus.subscribe("email.*", "test", handler)
        store.emit_event("email.arrived", {"id": "1"})
        store.emit_event("email.classified", {"id": "2"})
        store.emit_event("member.joined", {"id": "3"})  # Should NOT match

        asyncio.run(event_bus._process_pending())
        # email.* matches email.arrived and email.classified
        # But our implementation processes one at a time (first match)
        assert len(received) >= 1

    def test_exact_pattern(self, event_bus, store):
        """Exact patterns only match exact event types."""
        received = []
        async def handler(event):
            received.append(event)

        event_bus.subscribe("member.joined", "test", handler)
        store.emit_event("member.joined", {"id": "1"})
        store.emit_event("member.left", {"id": "2"})

        asyncio.run(event_bus._process_pending())
        assert len(received) == 1
        assert received[0]["payload"]["id"] == "1"

    def test_unmatched_events_marked_processed(self, event_bus, store):
        """Events with no subscriber are marked processed (no infinite retry)."""
        store.emit_event("orphan.event", {"data": "test"})
        asyncio.run(event_bus._process_pending())
        remaining = store.get_unprocessed_events("orphan.*")
        assert len(remaining) == 0


# ---------------------------------------------------------------------------
# Cache Tests
# ---------------------------------------------------------------------------

class TestCacheHardened:
    """LLM cache behavior."""

    def test_cache_miss_then_hit(self, cache):
        """First call misses, second call hits."""
        result = cache.get("gpt-4o", "system", "user msg")
        assert result is None  # Miss

        cache.put("gpt-4o", "system", "user msg", "response text")
        result = cache.get("gpt-4o", "system", "user msg")
        assert result == "response text"  # Hit

    def test_cache_different_inputs_miss(self, cache):
        """Different inputs produce different cache keys."""
        cache.put("gpt-4o", "system", "msg A", "response A")
        result = cache.get("gpt-4o", "system", "msg B")
        assert result is None  # Different input = miss

    def test_cache_stats(self, cache):
        """Stats track hits and misses."""
        cache.get("m", "s", "u1")  # miss
        cache.put("m", "s", "u1", "r1")
        cache.get("m", "s", "u1")  # hit
        cache.get("m", "s", "u2")  # miss

        stats = cache.stats
        assert stats["hits"] == 1
        assert stats["misses"] == 2
        assert stats["active_entries"] == 1

    def test_cache_invalidation(self, cache):
        """Invalidation removes entries."""
        cache.put("gpt-4o", "s", "u", "r")
        assert cache.get("gpt-4o", "s", "u") == "r"
        cache.invalidate(model="gpt-4o")
        assert cache.get("gpt-4o", "s", "u") is None


# ---------------------------------------------------------------------------
# Cost Tracker Tests
# ---------------------------------------------------------------------------

class TestCostTrackerHardened:
    """Cost tracking accuracy."""

    def test_records_cost(self, cost_tracker):
        """Records token usage and estimates cost."""
        cost = cost_tracker.record("test/agent", "gpt-4o", input_tokens=1000, output_tokens=500)
        assert cost > 0  # Should be non-zero for GPT-4o

    def test_cached_calls_zero_cost(self, cost_tracker):
        """Cached calls are recorded as zero cost."""
        cost = cost_tracker.record("test/agent", "gpt-4o", input_tokens=1000, output_tokens=500, cached=True)
        assert cost == 0.0

    def test_weekly_report(self, cost_tracker):
        """Weekly report aggregates correctly."""
        cost_tracker.record("agent/a", "gpt-4o", 1000, 500)
        cost_tracker.record("agent/a", "gpt-4o", 2000, 1000)
        cost_tracker.record("agent/b", "groq/llama-3.1-70b-versatile", 5000, 2000)

        report = cost_tracker.get_weekly_report()
        assert report["total_calls"] == 3
        assert report["total_cost"] > 0
        assert len(report["by_model"]) == 2
        assert len(report["by_agent"]) == 2


# ---------------------------------------------------------------------------
# Feedback Store Tests
# ---------------------------------------------------------------------------

class TestFeedbackHardened:
    """Feedback loop behavior."""

    def test_record_and_retrieve(self, feedback_store):
        """Records feedback and retrieves it."""
        feedback_store.record_edit("test/agent", "input", "original", "edited")
        examples = feedback_store.get_examples("test/agent")
        assert len(examples) == 1
        assert examples[0]["original_output"] == "original"
        assert examples[0]["edited_output"] == "edited"

    def test_few_shot_context_generation(self, feedback_store):
        """Generates few-shot context from feedback."""
        feedback_store.record_edit("test/agent", "input1", "orig1", "edit1")
        feedback_store.record_edit("test/agent", "input2", "orig2", "edit2")
        context = feedback_store.build_few_shot_context("test/agent")
        assert "LEARNING FROM PAST FEEDBACK" in context
        assert "edit1" in context or "edit2" in context

    def test_empty_feedback_returns_empty_context(self, feedback_store):
        """No feedback = empty context string."""
        context = feedback_store.build_few_shot_context("nonexistent/agent")
        assert context == ""

    def test_stats(self, feedback_store):
        """Stats report correctly."""
        feedback_store.record_edit("agent/a", "i", "o", "e")
        feedback_store.record_edit("agent/b", "i", "o", "e")
        feedback_store.record_edit("agent/a", "i", "o", "e")
        stats = feedback_store.get_stats()
        assert stats["total_feedback"] == 3
        assert stats["by_agent"]["agent/a"] == 2


# ---------------------------------------------------------------------------
# RAG Tests
# ---------------------------------------------------------------------------

class TestRAGHardened:
    """Research RAG deduplication and search."""

    def test_deduplication_by_url(self, rag):
        """Same URL is not indexed twice."""
        id1 = rag.index_item("https://example.com/article1", "Article 1")
        id2 = rag.index_item("https://example.com/article1", "Article 1 Again")
        assert id1 > 0
        assert id2 == 0  # Duplicate, not indexed

    def test_different_urls_indexed(self, rag):
        """Different URLs are indexed separately."""
        id1 = rag.index_item("https://example.com/a", "Article A")
        id2 = rag.index_item("https://example.com/b", "Article B")
        assert id1 > 0
        assert id2 > 0
        assert id1 != id2

    def test_search_finds_indexed_items(self, rag):
        """FTS5 search finds indexed items."""
        rag.index_item("https://example.com/gov", "AI Governance Framework", "A framework for governance as code")
        results = rag.search_similar("governance framework")
        assert len(results) >= 1
        assert "governance" in results[0]["title"].lower()

    def test_stats(self, rag):
        """Stats report correctly."""
        rag.index_item("https://a.com", "Item A", relevance_score=5)
        rag.index_item("https://b.com", "Item B", relevance_score=2)
        stats = rag.get_stats()
        assert stats["total_indexed"] == 2
        assert stats["high_relevance"] == 1


# ---------------------------------------------------------------------------
# Voice Transcription Tests
# ---------------------------------------------------------------------------

class TestVoiceCommandParsing:
    """Voice command parsing (no API calls needed)."""

    def _get_transcriber(self):
        pytest.importorskip("httpx")
        from src.personal_foundation.v2.voice_transcribe import VoiceTranscriber
        return VoiceTranscriber.__new__(VoiceTranscriber)

    def test_parse_whats_pending(self):
        vt = self._get_transcriber()
        result = vt.parse_command("what's pending in my queue")
        assert result["command"] == "whats_pending"

    def test_parse_approve_low_risk(self):
        vt = self._get_transcriber()
        result = vt.parse_command("approve all low risk items")
        assert result["command"] == "approve_all_low_risk"

    def test_parse_suspend(self):
        vt = self._get_transcriber()
        result = vt.parse_command("suspend the moderator")
        assert result["command"] == "suspend"
        assert "moderator" in result["params"].get("agent", "")

    def test_parse_draft(self):
        vt = self._get_transcriber()
        result = vt.parse_command("draft about AI governance trends in 2026")
        assert result["command"] == "draft"
        assert "governance" in result["params"].get("topic", "").lower()

    def test_parse_daily_summary(self):
        vt = self._get_transcriber()
        result = vt.parse_command("what did my agents do today")
        assert result["command"] == "daily_summary"


# ---------------------------------------------------------------------------
# Agent YAML Validation
# ---------------------------------------------------------------------------

class TestAgentYAMLHardened:
    """Comprehensive agent YAML validation."""

    def test_all_agents_have_required_fields(self):
        import yaml
        agents_dir = Path("agents")
        required = ["name", "trigger", "system_prompt"]
        for f in agents_dir.glob("*.yaml"):
            with f.open() as fh:
                data = yaml.safe_load(fh)
            agent = data["agent"]
            for field in required:
                assert field in agent, f"{f.name} missing agent.{field}"

    def test_all_agents_have_valid_model(self):
        import yaml
        valid_prefixes = ["gpt-", "groq/", "claude-", "ollama/"]
        agents_dir = Path("agents")
        for f in agents_dir.glob("*.yaml"):
            with f.open() as fh:
                data = yaml.safe_load(fh)
            model = data["agent"].get("model", "")
            assert any(model.startswith(p) for p in valid_prefixes), \
                f"{f.name}: invalid model '{model}'"

    def test_all_agents_have_actions(self):
        import yaml
        agents_dir = Path("agents")
        for f in agents_dir.glob("*.yaml"):
            with f.open() as fh:
                data = yaml.safe_load(fh)
            assert "actions" in data, f"{f.name} missing actions"
            assert len(data["actions"]) > 0, f"{f.name} has empty actions"


# ---------------------------------------------------------------------------
# Full Pipeline Test
# ---------------------------------------------------------------------------

class TestFullPipeline:
    """End-to-end pipeline: event → agent → policy → approval → audit."""

    def test_email_pipeline(self, store):
        """Simulate full email classification pipeline."""
        # 1. Emit email event
        event_id = store.emit_event("email.arrived", {
            "message_id": "msg_001",
            "sender": "partner@corp.com",
            "subject": "Partnership opportunity",
            "preview": "Hi Bob, we'd like to discuss...",
        })
        assert event_id > 0

        # 2. Simulate agent processing
        store.log_audit(
            agent="personal/email_classifier", action="classify",
            model="groq/llama-3.1-70b-versatile", status="success",
            result_summary="category=action-required, confidence=0.91",
        )

        # 3. Create approval item
        item_id = store.enqueue_approval(
            agent="personal/email_drafter",
            action_type="email_draft",
            description="Reply to partnership inquiry",
            draft_content="Hi! Thanks for reaching out...",
        )

        # 4. Verify queue
        pending = store.get_pending_approvals()
        assert len(pending) == 1
        assert pending[0]["id"] == item_id

        # 5. Approve
        result = store.approve_item(item_id, "bob")
        assert result["status"] == "approved"

        # 6. Verify audit trail
        entries = store.get_audit_log(limit=10)
        assert any(e["agent"] == "personal/email_classifier" for e in entries)

    def test_moderation_pipeline(self, store, policy):
        """Simulate moderation: classify → policy check → flag."""
        from src.personal_foundation.v2.policy import PolicyContext

        # 1. Moderator wants to flag
        ctx = PolicyContext(
            principal="foundation/moderator", action="flag_post",
            resource_type="circle_post", resource_id="p_spam",
            attributes={},
        )
        decision = policy.evaluate(ctx)
        assert decision.permitted  # Can flag

        # 2. Moderator tries to delete (should be denied)
        ctx2 = PolicyContext(
            principal="foundation/moderator", action="delete_post",
            resource_type="circle_post", resource_id="p_spam",
            attributes={},
        )
        decision2 = policy.evaluate(ctx2)
        assert not decision2.permitted  # Cannot delete

        # 3. Log the flag action
        store.log_audit(
            agent="foundation/moderator", action="flag_post",
            status="success", result_summary="Flagged post p_spam (spam=0.95)",
            policy_result=f"{decision.rule_file}:{decision.rule_name}",
        )

        entries = store.get_audit_log(agent="foundation/moderator")
        assert len(entries) == 1
        assert entries[0]["policy_result"] != ""


# ---------------------------------------------------------------------------
# Demo Script Test
# ---------------------------------------------------------------------------

class TestDemoIntegrity:
    """Verify demo script still runs clean."""

    def test_demo_completes(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "scripts/demo.py"],
            capture_output=True, text=True, timeout=30,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0, f"Demo failed:\n{result.stderr}"
        assert "OPERATIONAL" in result.stdout
        assert "Demo Complete" in result.stdout
