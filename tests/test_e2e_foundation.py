"""End-to-end tests for the personal + foundation automation system.

Tests the full pipeline in dry-run mode:
- Config loading
- Profile loading (bob, ken)
- Agent instantiation
- Approval Queue flow
- Audit log writing
- No cross-imports with customer code

Run: pytest tests/test_e2e_foundation.py -v
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure we can import the package
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestConfigLoading:
    """Test that config loads and validates correctly."""

    def test_config_example_exists(self):
        """config.example.yaml exists and is valid YAML."""
        import yaml
        example = Path("config/personal-foundation/config.example.yaml")
        assert example.exists(), f"Missing: {example}"
        with example.open() as f:
            data = yaml.safe_load(f)
        assert "telegram" in data
        assert "circle" in data
        assert "composio" in data
        assert "perplexity" in data

    def test_config_loads_with_valid_yaml(self, tmp_path):
        """FoundationConfig loads from a valid YAML file."""
        from src.personal_foundation.config import FoundationConfig, load_config

        config_data = {
            "telegram": {
                "bot_token": "123456:ABC",
                "approval_chat_id": "111",
                "bob_chat_id": "222",
                "ken_chat_id": "333",
            },
            "circle": {
                "api_key": "ck_test",
                "community_id": "c1",
                "welcome_space_id": "s1",
                "digest_space_id": "s2",
                "headless_auth_jwt": "jwt_test",
            },
            "composio": {
                "api_key": "comp_test",
                "asana_workspace_id": "aw1",
                "trello_board_id": "tb1",
            },
            "perplexity": {"api_key": "pplx_test"},
            "dry_run": True,
        }

        import yaml
        config_file = tmp_path / "config.yaml"
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        cfg = load_config(str(config_file))
        assert cfg.dry_run is True
        assert cfg.telegram.bot_token == "123456:ABC"
        assert cfg.circle.api_key == "ck_test"

    def test_config_missing_raises(self):
        """load_config raises FileNotFoundError for missing file."""
        from src.personal_foundation.config import load_config
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/config.yaml")


class TestProfiles:
    """Test profile loading and versioning."""

    def test_bob_profile_exists(self):
        """Bob's v1 profile exists and loads."""
        from src.personal_foundation.profiles import load_profile
        profile = load_profile("bob", "1")
        assert profile.name == "Bob Rapp"
        assert profile.version == "1.0.0"
        assert profile.stage == "production"
        assert "personal/email_agent" in profile.agents
        assert profile.agents["personal/email_agent"].enabled is True

    def test_ken_profile_exists(self):
        """Ken's v1 profile exists and loads."""
        from src.personal_foundation.profiles import load_profile
        profile = load_profile("ken", "1")
        assert profile.name == "Ken Johnston"
        assert profile.version == "1.0.0"
        assert profile.stage == "staging"
        # Ken starts with email disabled
        assert profile.agents["personal/email_agent"].enabled is False
        # But research is enabled
        assert profile.agents["personal/research_agent"].enabled is True

    def test_list_profiles(self):
        """list_profiles returns both bob and ken."""
        from src.personal_foundation.profiles import list_profiles
        profiles = list_profiles()
        operators = [p["operator"] for p in profiles]
        assert "bob" in operators
        assert "ken" in operators

    def test_bob_has_more_agents_than_ken(self):
        """Bob has all agents enabled; Ken has a subset."""
        from src.personal_foundation.profiles import load_profile
        bob = load_profile("bob", "1")
        ken = load_profile("ken", "1")
        assert len(bob.enabled_agents) > len(ken.enabled_agents)

    def test_bob_workflows(self):
        """Bob has 4 workflows defined."""
        from src.personal_foundation.profiles import load_profile
        bob = load_profile("bob", "1")
        assert len(bob.workflows) == 4
        names = [w.name for w in bob.workflows]
        assert "Daily Morning Routine" in names
        assert "Weekly Reports (Friday)" in names

    def test_ken_workflows(self):
        """Ken has 3 workflows (lighter than Bob)."""
        from src.personal_foundation.profiles import load_profile
        ken = load_profile("ken", "1")
        assert len(ken.workflows) == 3


class TestAuditShim:
    """Test the audit shim enforces prefixes."""

    def test_valid_prefix_passes(self):
        """Actions with personal/ or foundation/ prefix pass."""
        from src.personal_foundation.audit_shim import log_action
        with patch("src.audit_log.log_action") as mock:
            mock.return_value = MagicMock()
            log_action(action="personal/email_agent:classify", command="test")
            mock.assert_called_once()

    def test_invalid_prefix_raises(self):
        """Actions without prefix raise ValueError."""
        from src.personal_foundation.audit_shim import log_action
        with pytest.raises(ValueError, match="must start with"):
            log_action(action="email_agent:classify", command="test")

    def test_foundation_prefix_passes(self):
        """foundation/ prefix is valid."""
        from src.personal_foundation.audit_shim import log_action
        with patch("src.audit_log.log_action") as mock:
            mock.return_value = MagicMock()
            log_action(action="foundation/welcomer:send_dm", command="test")
            mock.assert_called_once()


class TestApprovalQueue:
    """Test the Approval Queue state machine."""

    def test_enqueue_and_retrieve(self):
        """Items can be enqueued and retrieved."""
        from src.personal_foundation.approval_queue import ApprovalItem, ApprovalQueue
        q = ApprovalQueue()
        item = ApprovalItem(
            agent="personal/email_agent",
            action_type="email_draft",
            description="Test draft",
            draft_content="Hello world",
        )
        q.enqueue(item)
        assert len(q.pending()) == 1
        assert q.pending()[0].agent == "personal/email_agent"

    def test_approve_flow(self):
        """Approving an item changes its status."""
        from src.personal_foundation.approval_queue import ApprovalItem, ApprovalQueue
        q = ApprovalQueue()
        item = ApprovalItem(
            agent="foundation/curator",
            action_type="weekly_digest",
            description="Digest",
            draft_content="Content",
        )
        q.enqueue(item)
        approved = q.approve(item.item_id, "bob")
        assert approved.status == "approved"
        assert approved.reviewer == "bob"
        assert len(q.pending()) == 0

    def test_reject_flow(self):
        """Rejecting an item records the reason."""
        from src.personal_foundation.approval_queue import ApprovalItem, ApprovalQueue
        q = ApprovalQueue()
        item = ApprovalItem(
            agent="foundation/moderator",
            action_type="redirect_comment",
            description="Redirect",
            draft_content="Please move this",
        )
        q.enqueue(item)
        rejected = q.reject(item.item_id, "ken", "Too aggressive")
        assert rejected.status == "rejected"
        assert rejected.rejection_reason == "Too aggressive"

    def test_edit_flow(self):
        """Editing replaces content and sets status to edited."""
        from src.personal_foundation.approval_queue import ApprovalItem, ApprovalQueue
        q = ApprovalQueue()
        item = ApprovalItem(
            agent="personal/task_agent",
            action_type="outreach_followup",
            description="Follow up",
            draft_content="Original",
        )
        q.enqueue(item)
        edited = q.edit(item.item_id, "Revised content")
        assert edited.draft_content == "Revised content"
        assert edited.status == "edited"
        # Edited items still appear in pending
        assert len(q.pending()) == 1

    def test_duplicate_enqueue_raises(self):
        """Enqueueing the same item_id twice raises."""
        from src.personal_foundation.approval_queue import ApprovalItem, ApprovalQueue
        q = ApprovalQueue()
        item = ApprovalItem(
            agent="personal/email_agent",
            action_type="test",
            description="Test",
            draft_content="Content",
            item_id="fixed-id",
        )
        q.enqueue(item)
        with pytest.raises(ValueError):
            q.enqueue(item)


class TestAgentInstantiation:
    """Test that all agents can be instantiated in dry-run mode."""

    def _mock_config(self):
        config = MagicMock()
        config.dry_run = True
        config.max_emails_per_hour = 50
        config.circle = MagicMock()
        config.circle.welcome_space_id = "s1"
        config.telegram = MagicMock()
        config.telegram.bob_chat_id = "123"
        config.telegram.ken_chat_id = "456"
        return config

    def test_email_agent(self):
        from src.personal_foundation.agents.email_agent import EmailAgent
        agent = EmailAgent(config=self._mock_config(), dry_run=True)
        assert agent.full_agent_name == "personal/email_agent"

    def test_calendar_agent(self):
        from src.personal_foundation.agents.calendar_agent import CalendarAgent
        agent = CalendarAgent(config=self._mock_config(), dry_run=True)
        assert agent.full_agent_name == "personal/calendar_agent"

    def test_research_agent(self):
        from src.personal_foundation.agents.research_agent import ResearchAgent
        agent = ResearchAgent(config=self._mock_config(), dry_run=True)
        assert agent.full_agent_name == "personal/research_agent"

    def test_writing_agent(self):
        from src.personal_foundation.agents.writing_agent import WritingAgent
        agent = WritingAgent(config=self._mock_config(), dry_run=True)
        assert agent.full_agent_name == "foundation/writing_agent"

    def test_task_agent(self):
        from src.personal_foundation.agents.task_agent import TaskAgent
        agent = TaskAgent(config=self._mock_config(), dry_run=True)
        assert agent.full_agent_name == "personal/task_agent"

    def test_welcomer(self):
        from src.personal_foundation.agents.welcomer import Welcomer
        agent = Welcomer(config=self._mock_config(), dry_run=True)
        assert agent.full_agent_name == "foundation/welcomer"

    def test_curator(self):
        from src.personal_foundation.agents.curator import Curator
        agent = Curator(config=self._mock_config(), dry_run=True)
        assert agent.full_agent_name == "foundation/curator"

    def test_moderator(self):
        from src.personal_foundation.agents.moderator import Moderator
        agent = Moderator(config=self._mock_config(), dry_run=True)
        assert agent.full_agent_name == "foundation/moderator"


class TestModels:
    """Test data model round-trips and properties."""

    def test_research_item_roundtrip(self):
        """ResearchItem serializes and deserializes correctly."""
        from datetime import datetime, timezone
        from src.personal_foundation.models import ResearchItem

        item = ResearchItem(
            item_id="test-1",
            source_url="https://example.com/article",
            title="AI Governance Framework",
            published_at=datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc),
            pillar_scores={"governance_as_code": 5, "ai_technical_debt": 3,
                          "operational_compliance": 4, "community_driven_standards": 2},
            relevance_score=5,
            scan_session_id="session-1",
            summary="A framework for governance as code.",
        )
        serialized = item.to_json()
        recovered = ResearchItem.from_json(serialized)
        assert recovered.pillar_scores == item.pillar_scores
        assert recovered.summary == item.summary
        assert recovered.relevance_score == item.relevance_score

    def test_circle_post_engagement(self):
        """CirclePost.engagement = reactions + comments."""
        from datetime import datetime, timezone
        from src.personal_foundation.models import CirclePost

        post = CirclePost(
            post_id="p1", space_id="s1", author_member_id="m1",
            title="Test", body="Body",
            published_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
            reactions=10, comments=5,
        )
        assert post.engagement == 15

    def test_pipeline_stage_values(self):
        """PipelineStage enum has all expected values."""
        from src.personal_foundation.models import PipelineStage
        assert PipelineStage.NEW.value == "new"
        assert PipelineStage.ARCHIVED.value == "archived"
        assert len(PipelineStage) == 7


class TestNoCustomerCrossImports:
    """Verify src/personal_foundation has no imports from customer code."""

    def test_no_setup_agent_import(self):
        """No file in src/personal_foundation/ imports from src.setup_agent."""
        import ast
        pkg_dir = Path("src/personal_foundation")
        violations = []
        for py_file in pkg_dir.rglob("*.py"):
            with py_file.open() as f:
                try:
                    tree = ast.parse(f.read())
                except SyntaxError:
                    continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if "setup_agent" in alias.name or "hermes_install" in alias.name:
                            violations.append(f"{py_file}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module and ("setup_agent" in node.module or "hermes_install" in node.module):
                        violations.append(f"{py_file}: from {node.module}")
        assert violations == [], f"Cross-imports found: {violations}"


class TestGitignore:
    """Verify config is properly gitignored."""

    def test_config_yaml_gitignored(self):
        """config/personal-foundation/config.yaml is in .gitignore."""
        gitignore = Path(".gitignore").read_text()
        assert "config/personal-foundation/config.yaml" in gitignore
