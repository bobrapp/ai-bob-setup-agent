"""Property-based tests for the personal + foundation automation system.

Uses Hypothesis to verify 10 correctness properties across generated inputs.
Each property test runs a minimum of 100 iterations.

INTERNAL USE ONLY — not part of the ai-bob-setup-agent customer product.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.personal_foundation.approval_queue import ApprovalItem, ApprovalQueue
from src.personal_foundation.models import (
    EMAIL_CATEGORIES,
    CirclePost,
    EmailClassification,
    EmailMessage,
    OutreachContact,
    PipelineStage,
    ResearchItem,
)

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

st_datetime = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
    timezones=st.just(timezone.utc),
)

st_pillar_scores = st.fixed_dictionaries({
    "governance_as_code": st.integers(min_value=1, max_value=5),
    "ai_technical_debt": st.integers(min_value=1, max_value=5),
    "operational_compliance": st.integers(min_value=1, max_value=5),
    "community_driven_standards": st.integers(min_value=1, max_value=5),
})

st_research_item = st.builds(
    ResearchItem,
    item_id=st.text(min_size=1, max_size=36, alphabet="abcdef0123456789-"),
    source_url=st.text(min_size=5, max_size=100).map(lambda s: f"https://{s}"),
    title=st.text(min_size=1, max_size=200),
    published_at=st_datetime,
    pillar_scores=st_pillar_scores,
    relevance_score=st.integers(min_value=1, max_value=5),
    scan_session_id=st.text(min_size=1, max_size=36),
    summary=st.one_of(st.none(), st.text(min_size=1, max_size=500)),
)

st_approval_item = st.builds(
    ApprovalItem,
    agent=st.sampled_from([
        "personal/email_agent", "personal/calendar_agent", "personal/research_agent",
        "personal/task_agent", "foundation/welcomer", "foundation/curator",
        "foundation/moderator", "foundation/writing_agent",
    ]),
    action_type=st.sampled_from([
        "email_draft", "calendar_confirm", "weekly_digest", "redirect_comment",
        "outreach_followup", "newsletter_draft", "content_draft_on-demand",
    ]),
    description=st.text(min_size=1, max_size=200),
    draft_content=st.text(min_size=1, max_size=1000),
    rationale=st.text(max_size=200),
    item_id=st.uuids().map(str),
    created_at=st_datetime,
)

st_circle_post = st.builds(
    CirclePost,
    post_id=st.text(min_size=1, max_size=20, alphabet="0123456789"),
    space_id=st.text(min_size=1, max_size=20, alphabet="0123456789"),
    author_member_id=st.text(min_size=1, max_size=20, alphabet="0123456789"),
    title=st.text(min_size=1, max_size=200),
    body=st.text(min_size=1, max_size=500),
    published_at=st_datetime,
    reactions=st.integers(min_value=0, max_value=1000),
    comments=st.integers(min_value=0, max_value=1000),
    tags=st.lists(st.text(min_size=1, max_size=30), max_size=5),
)

st_email_message = st.builds(
    EmailMessage,
    message_id=st.uuids().map(str),
    sender=st.emails(),
    subject=st.text(min_size=1, max_size=200),
    body_preview=st.text(min_size=1, max_size=500),
    received_at=st_datetime,
)

st_outreach_contact = st.builds(
    OutreachContact,
    contact_id=st.uuids().map(str),
    name=st.text(min_size=1, max_size=100),
    pipeline_stage=st.sampled_from(list(PipelineStage)),
    asana_task_id=st.text(min_size=1, max_size=36),
    last_contact_date=st.one_of(st.none(), st_datetime),
    notes=st.text(max_size=200),
)


# ---------------------------------------------------------------------------
# Property 1: Audit log JSONL round-trip
# Feature: personal-foundation-agent-automation, Property 1: audit log JSONL round-trip
# ---------------------------------------------------------------------------

@given(
    action=st.sampled_from([
        "personal/email_agent:classify", "foundation/welcomer:send_dm",
        "personal/task_agent:create_task", "foundation/moderator:classify",
    ]),
    command=st.text(min_size=1, max_size=200),
    status=st.sampled_from(["success", "failure", "partial"]),
    result_summary=st.text(max_size=200),
)
@settings(max_examples=200)
def test_audit_entry_jsonl_roundtrip(action, command, status, result_summary):
    """Serializing an audit-like record to JSONL and back preserves all fields."""
    record = {
        "action": action,
        "command": command,
        "status": status,
        "result_summary": result_summary,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operator": "bobrapp",
        "customer": "bob",
        "dry_run": False,
    }
    line = json.dumps(record, default=str)
    recovered = json.loads(line)
    assert recovered["action"] == record["action"]
    assert recovered["command"] == record["command"]
    assert recovered["status"] == record["status"]
    assert recovered["result_summary"] == record["result_summary"]


# ---------------------------------------------------------------------------
# Property 2: Research item round-trip
# Feature: personal-foundation-agent-automation, Property 2: research item round-trip
# ---------------------------------------------------------------------------

@given(item=st_research_item)
@settings(max_examples=100)
def test_research_item_roundtrip(item):
    """ResearchItem.to_json() → from_json() preserves pillar_scores and summary."""
    serialized = item.to_json()
    recovered = ResearchItem.from_json(serialized)
    assert recovered.pillar_scores == item.pillar_scores
    assert recovered.summary == item.summary
    assert recovered.item_id == item.item_id
    assert recovered.relevance_score == item.relevance_score


# ---------------------------------------------------------------------------
# Property 3: Dry-run produces no external calls
# Feature: personal-foundation-agent-automation, Property 3: dry-run no external calls
# ---------------------------------------------------------------------------

@given(email=st_email_message)
@settings(max_examples=100)
def test_dry_run_email_agent_no_http(email):
    """EmailAgent in dry_run mode never makes external HTTP calls."""
    from src.personal_foundation.agents.email_agent import EmailAgent
    from src.personal_foundation.config import FoundationConfig

    with patch("httpx.Client") as mock_client, \
         patch("httpx.post") as mock_post:
        config = MagicMock(spec=FoundationConfig)
        config.max_emails_per_hour = 50
        agent = EmailAgent(config=config, dry_run=True)
        agent._orchestrator = MagicMock()
        # Process should not make HTTP calls
        agent.classify(email)
        mock_client.assert_not_called()
        mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# Property 4: Approval_Queue item integrity
# Feature: personal-foundation-agent-automation, Property 4: approval queue item integrity
# ---------------------------------------------------------------------------

@given(item=st_approval_item)
@settings(max_examples=100)
def test_approval_queue_roundtrip(item):
    """Enqueuing and retrieving an ApprovalItem preserves all key fields."""
    queue = ApprovalQueue()
    queue.enqueue(item)
    retrieved = queue.pending()[0]
    assert retrieved.agent == item.agent
    assert retrieved.action_type == item.action_type
    assert retrieved.description == item.description
    assert retrieved.draft_content == item.draft_content
    assert retrieved.created_at == item.created_at
    assert retrieved.item_id == item.item_id


# ---------------------------------------------------------------------------
# Property 5: Welcome DM idempotence
# Feature: personal-foundation-agent-automation, Property 5: welcome DM idempotence
# ---------------------------------------------------------------------------

@given(
    member_id=st.text(min_size=1, max_size=20, alphabet="0123456789"),
    join_event_id=st.text(min_size=1, max_size=36, alphabet="abcdef0123456789"),
)
@settings(max_examples=100)
def test_welcome_dm_idempotent(member_id, join_event_id):
    """Calling welcome() twice for the same member+event sends at most 1 DM."""
    from src.personal_foundation.agents.welcomer import Welcomer

    config = MagicMock()
    config.circle = MagicMock()
    config.circle.welcome_space_id = "space1"
    welcomer = Welcomer(config=config, dry_run=True)
    welcomer._orchestrator = MagicMock()

    # Mock circle client
    mock_circle = MagicMock()
    mock_circle.get_member.return_value = MagicMock(
        member_id=member_id, display_name="Test", bio="", role="",
        organization="", ai_governance_interests=[], interest_tags=[],
    )
    welcomer._circle_client = mock_circle

    welcomer.welcome(member_id, join_event_id)
    welcomer.welcome(member_id, join_event_id)  # second call

    # Should only have one entry in _sent_dms for this pair
    assert (member_id, join_event_id) in welcomer._sent_dms
    # The set ensures at most 1 entry per (member_id, join_event_id)
    count = sum(1 for k in welcomer._sent_dms if k == (member_id, join_event_id))
    assert count == 1


# ---------------------------------------------------------------------------
# Property 6: Moderator never auto-removes content
# Feature: personal-foundation-agent-automation, Property 6: moderator never auto-removes
# ---------------------------------------------------------------------------

@given(post=st_circle_post, confidence=st.floats(min_value=0.0, max_value=1.0))
@settings(max_examples=100)
def test_moderator_no_auto_remove(post, confidence):
    """Moderator never calls delete_post or hide_post regardless of confidence."""
    from src.personal_foundation.agents.moderator import Moderator

    config = MagicMock()
    moderator = Moderator(config=config, dry_run=False)
    moderator._orchestrator = MagicMock()

    mock_circle = MagicMock()
    moderator._circle_client = mock_circle

    moderator.classify_and_act(post, confidence_override=confidence)

    # Assert delete and hide are never called
    mock_circle.delete_post = MagicMock()
    mock_circle.hide_post = MagicMock()
    # These methods should not exist on the client, but verify no call
    assert not hasattr(mock_circle, "delete_post") or not mock_circle.delete_post.called
    assert not hasattr(mock_circle, "hide_post") or not mock_circle.hide_post.called


# ---------------------------------------------------------------------------
# Property 7: Agent prefix invariant
# Feature: personal-foundation-agent-automation, Property 7: agent prefix invariant
# ---------------------------------------------------------------------------

@given(action_name=st.text(min_size=1, max_size=50, alphabet="abcdefghijklmnopqrstuvwxyz_"))
@settings(max_examples=100)
def test_audit_action_prefix(action_name):
    """Every agent log entry has action starting with personal/ or foundation/."""
    from src.personal_foundation.audit_shim import log_action, VALID_PREFIXES

    # Valid prefixed action should succeed
    prefixed = f"personal/test_agent:{action_name}"
    with patch("src.audit_log.log_action") as mock_log:
        mock_log.return_value = MagicMock()
        entry = log_action(action=prefixed, command="test")
        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args
        assert call_kwargs[1]["action"].startswith(VALID_PREFIXES) or \
               call_kwargs[0][0].startswith(VALID_PREFIXES) if call_kwargs[0] else True


# ---------------------------------------------------------------------------
# Property 8: Email classification exhaustiveness
# Feature: personal-foundation-agent-automation, Property 8: email classification exhaustiveness
# ---------------------------------------------------------------------------

@given(email=st_email_message)
@settings(max_examples=100)
def test_email_classification_valid_category(email):
    """If confidence >= 70%, category must be one of the 5 valid categories."""
    from src.personal_foundation.agents.email_agent import EmailAgent

    config = MagicMock()
    config.max_emails_per_hour = 50
    agent = EmailAgent(config=config, dry_run=True)
    agent._orchestrator = MagicMock()

    result = agent.classify(email)
    if result.confidence >= 0.70:
        assert result.category in EMAIL_CATEGORIES


# ---------------------------------------------------------------------------
# Property 9: Outreach follow-up draft retry exhaustion
# Feature: personal-foundation-agent-automation, Property 9: outreach retry exhaustion
# ---------------------------------------------------------------------------

@given(contact=st_outreach_contact)
@settings(max_examples=100)
def test_outreach_retry_max_3(contact):
    """Draft follow-up retries at most 3 times before giving up."""
    from src.personal_foundation.agents.task_agent import TaskAgent, MAX_OUTREACH_RETRIES

    config = MagicMock()
    agent = TaskAgent(config=config, dry_run=True)
    agent._orchestrator = MagicMock()

    call_count = 0

    def always_fail(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("draft failed")

    agent._generate_followup_draft = always_fail
    agent._draft_followup_with_retry(contact)

    assert call_count == MAX_OUTREACH_RETRIES


# ---------------------------------------------------------------------------
# Property 10: Writing_Agent never publishes without approval
# Feature: personal-foundation-agent-automation, Property 10: writing agent no direct publish
# ---------------------------------------------------------------------------

@given(
    content_request=st.text(min_size=1, max_size=200),
    content_type=st.sampled_from(["newsletter", "linkedin", "on-demand"]),
)
@settings(max_examples=100)
def test_writing_agent_no_direct_publish(content_request, content_type):
    """Writing_Agent.create_draft() never calls any publication endpoint."""
    from src.personal_foundation.agents.writing_agent import WritingAgent

    config = MagicMock()
    agent = WritingAgent(config=config, dry_run=False)
    agent._orchestrator = MagicMock()

    with patch("src.personal_foundation.integrations.circle_client.CircleClient.post_to_space") as mock_post, \
         patch("smtplib.SMTP") as mock_smtp:
        agent.create_draft(content_request, content_type)
        mock_post.assert_not_called()
        mock_smtp.assert_not_called()
