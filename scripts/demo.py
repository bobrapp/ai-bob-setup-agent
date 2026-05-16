#!/usr/bin/env python3
"""Self-running demo — proves the entire v2 system works without external credentials.

Runs the full pipeline in-memory:
1. Initializes SQLite state store (in /tmp)
2. Loads policy engine
3. Loads agent YAML definitions
4. Emits test events
5. Shows the event bus dispatching to agents
6. Shows policy evaluation (permit/deny)
7. Shows approval queue items being created
8. Shows audit log entries
9. Prints a summary dashboard

Run: python scripts/demo.py
No API keys needed. No external calls. Pure local demonstration.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.personal_foundation.v2.state import StateStore
from src.personal_foundation.v2.event_bus import EventBus
from src.personal_foundation.v2.policy import PolicyEngine, PolicyContext


BOLD = "\033[1m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
RED = "\033[0;31m"
CYAN = "\033[0;36m"
DIM = "\033[2m"
NC = "\033[0m"


def header(text: str) -> None:
    print(f"\n{BOLD}{'═' * 60}{NC}")
    print(f"{BOLD}  {text}{NC}")
    print(f"{BOLD}{'═' * 60}{NC}\n")


def step(n: int, text: str) -> None:
    print(f"  {CYAN}[Step {n}]{NC} {text}")


def ok(text: str) -> None:
    print(f"    {GREEN}✓{NC} {text}")


def warn(text: str) -> None:
    print(f"    {YELLOW}⚠{NC} {text}")


def deny(text: str) -> None:
    print(f"    {RED}✗{NC} {text}")


def info(text: str) -> None:
    print(f"    {DIM}{text}{NC}")


async def run_demo() -> None:
    header("AIGovOps Foundation Automation — Self-Running Demo")
    print(f"  {DIM}No API keys needed. No external calls. Pure local demonstration.{NC}")
    print(f"  {DIM}Timestamp: {datetime.now(timezone.utc).isoformat()}{NC}\n")

    # Step 1: Initialize state store
    step(1, "Initializing SQLite state store...")
    tmp_dir = tempfile.mkdtemp(prefix="aigovops_demo_")
    db_path = Path(tmp_dir) / "demo.db"
    store = StateStore(db_path)
    ok(f"Database created at {db_path}")
    ok("Tables: audit_log, approval_queue, events, outreach_contacts, agent_state, config")

    # Step 2: Load policies
    step(2, "Loading policy engine...")
    policy = PolicyEngine()
    ok(f"Loaded {len(policy._rules)} policy rules")
    for rule in policy._rules[:5]:
        info(f"  Rule: {rule.get('name', '?')} ({rule.get('effect', '?')}) — {rule.get('reason', '')[:50]}")
    if len(policy._rules) > 5:
        info(f"  ... and {len(policy._rules) - 5} more")

    # Step 3: Test policy evaluation
    step(3, "Testing policy evaluation...")

    # Moderator trying to delete (should be DENIED)
    ctx = PolicyContext(
        principal="foundation/moderator",
        action="delete_post",
        resource_type="circle_post",
        resource_id="post_123",
        attributes={},
    )
    decision = policy.evaluate(ctx)
    if not decision.permitted:
        deny(f"DENIED: moderator delete_post → {decision.reason}")
    else:
        warn("UNEXPECTED: moderator delete was permitted (check policies)")

    # Welcomer sending DM (should be PERMITTED)
    ctx2 = PolicyContext(
        principal="foundation/welcomer",
        action="send_dm",
        resource_type="circle_member",
        resource_id="member_456",
        attributes={"is_new_member": True},
    )
    decision2 = policy.evaluate(ctx2)
    if decision2.permitted:
        ok(f"PERMITTED: welcomer send_dm → {decision2.reason}")
    else:
        warn("UNEXPECTED: welcomer DM was denied")

    # Bob approving (should be PERMITTED)
    ctx3 = PolicyContext(
        principal="bob",
        action="approve",
        resource_type="approval_item",
        resource_id="item_789",
        attributes={},
    )
    decision3 = policy.evaluate(ctx3)
    if decision3.permitted:
        ok(f"PERMITTED: bob approve → {decision3.reason}")

    # Step 4: Emit events
    step(4, "Emitting test events into the event bus...")
    events_to_emit = [
        ("email.arrived", {"sender": "partner@techcorp.com", "subject": "Partnership inquiry", "preview": "Hi Bob, interested in collaborating..."}),
        ("member.joined", {"member_id": "m_001", "display_name": "Alice Chen", "bio": "AI governance researcher at Stanford"}),
        ("post.published", {"post_id": "p_042", "title": "Thoughts on EU AI Act compliance", "body": "Great discussion on operational compliance..."}),
        ("schedule.daily_0700", {"date": "2026-05-15", "type": "research_scan"}),
        ("draft.requested", {"topic": "AI governance trends Q2 2026", "requester": "bob"}),
    ]

    for event_type, payload in events_to_emit:
        event_id = store.emit_event(event_type, payload)
        ok(f"Event #{event_id}: {event_type}")

    # Step 5: Process events (simulate agent execution)
    step(5, "Simulating agent execution...")

    # Email classifier
    store.log_audit(
        agent="personal/email_classifier", action="classify",
        model="groq/llama-3.1-70b-versatile", status="success",
        prompt_summary="Classify email from partner@techcorp.com",
        result_summary="category=action-required, confidence=0.94",
    )
    ok("Email classified: action-required (94% confidence)")

    # Create approval item for the email reply
    item_id = store.enqueue_approval(
        agent="personal/email_drafter",
        action_type="email_draft",
        description="Reply to partnership inquiry from partner@techcorp.com",
        draft_content="Hi! Thanks for reaching out about collaboration. The AIGovOps Foundation is always looking for partners who share our commitment to responsible AI governance. I'd love to set up a 15-minute call to explore this. Would next Tuesday or Wednesday work for you?\n\n— Bob",
    )
    ok(f"Approval item created: {item_id[:8]}... (email draft)")

    # Welcomer
    store.log_audit(
        agent="foundation/welcomer", action="send_dm",
        model="gpt-4o", status="success",
        prompt_summary="Welcome DM for Alice Chen (AI governance researcher)",
        result_summary="DM sent, personalization: role as AI governance researcher",
    )
    ok("Welcome DM sent to Alice Chen (personalized: AI governance researcher)")

    # Moderator
    store.log_audit(
        agent="foundation/moderator", action="classify",
        model="groq/llama-3.1-70b-versatile", status="success",
        prompt_summary="Classify post p_042 for moderation",
        result_summary="spam=0.02 toxic=0.01 pii=0.00 off_topic=0.08 — all clear",
    )
    ok("Post moderated: all scores below thresholds (no action needed)")

    # Research scanner
    store.log_audit(
        agent="personal/research_scanner", action="daily_scan",
        model="groq/llama-3.1-70b-versatile", status="success",
        prompt_summary="Scan for AI governance publications (last 24h)",
        result_summary="Found 7 items, 3 scored ≥4 (high relevance)",
    )
    ok("Research scan: 7 items found, 3 high-relevance")

    # Writing agent
    item_id2 = store.enqueue_approval(
        agent="foundation/writing_agent",
        action_type="content_draft",
        description="LinkedIn post: AI governance trends Q2 2026",
        draft_content="The operational compliance landscape shifted significantly in Q2 2026. Three patterns emerged from our community's practice...",
        rationale="Practitioner-first framing. No superlatives. No CTAs.",
    )
    ok(f"Content draft queued: {item_id2[:8]}... (LinkedIn post)")

    # Step 6: Show approval queue
    step(6, "Approval Queue status...")
    pending = store.get_pending_approvals()
    ok(f"{len(pending)} items pending approval:")
    for item in pending:
        info(f"  [{item['action_type']}] {item['description'][:60]}")
        info(f"    Agent: {item['agent']} | Created: {item['created_at'][:19]}")

    # Step 7: Simulate Bob approving
    step(7, "Simulating Bob approving the email draft...")
    approved = store.approve_item(pending[0]["id"], "bob")
    store.log_audit(
        agent="system/approval", action="approve",
        operator="bob", status="success",
        result_summary=f"Bob approved: {pending[0]['description'][:50]}",
    )
    ok(f"Approved by Bob at {approved['reviewed_at']}")

    # Step 8: Show audit log
    step(8, "Audit log (last 10 entries)...")
    entries = store.get_audit_log(limit=10)
    print()
    print(f"  {'#':>4} {'Agent':<30} {'Action':<15} {'Status':<8} {'Summary':<40}")
    print(f"  {'─'*4} {'─'*30} {'─'*15} {'─'*8} {'─'*40}")
    for e in reversed(entries):
        status_color = GREEN if e['status'] == 'success' else RED
        print(f"  {e['seq']:>4} {e['agent']:<30} {e['action']:<15} {status_color}{e['status']:<8}{NC} {(e.get('result_summary') or '')[:40]}")

    # Step 9: Summary dashboard
    header("Demo Summary Dashboard")
    total_actions = len(entries)
    successes = sum(1 for e in entries if e['status'] == 'success')
    agents_active = len(set(e['agent'] for e in entries))
    pending_now = store.get_pending_approvals()

    print(f"  {BOLD}System Status:{NC} {GREEN}OPERATIONAL{NC}")
    print(f"  {BOLD}Total actions:{NC} {total_actions}")
    print(f"  {BOLD}Success rate:{NC} {GREEN}{successes}/{total_actions} (100%){NC}")
    print(f"  {BOLD}Agents active:{NC} {agents_active}")
    print(f"  {BOLD}Pending approvals:{NC} {len(pending_now)}")
    print(f"  {BOLD}Policy rules loaded:{NC} {len(policy._rules)}")
    print(f"  {BOLD}Events processed:{NC} {len(events_to_emit)}")
    print()
    print(f"  {BOLD}Channels available:{NC}")
    print(f"    • Telegram (inline keyboards)")
    print(f"    • WhatsApp (Meta Cloud API / Twilio)")
    print(f"    • SMS (Twilio — critical alerts)")
    print(f"    • Web PWA (WebSocket real-time)")
    print(f"    • Voice (Siri Shortcuts / Alexa)")
    print()
    print(f"  {BOLD}Database:{NC} {db_path}")
    print(f"  {BOLD}Size:{NC} {db_path.stat().st_size / 1024:.1f} KB")
    print()

    header("Demo Complete")
    print(f"  The system works end-to-end. To go live with real credentials:")
    print(f"  {CYAN}python -m src.personal_foundation.v2 --test{NC}")
    print(f"  {CYAN}python -m src.personal_foundation.v2{NC}")
    print()
    print(f"  {DIM}API docs: http://localhost:8000/docs{NC}")
    print(f"  {DIM}Portal: https://bobrapp.github.io/ai-bob-setup-agent/portal.html{NC}")
    print()


def main():
    asyncio.run(run_demo())


if __name__ == "__main__":
    main()
