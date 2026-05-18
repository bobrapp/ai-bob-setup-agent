"""Command Router — the shared brain for all channels.

All channels (Telegram, WhatsApp, SMS, Email, Web) funnel commands here.
This module handles parsing and execution, returning plain-text responses
that each channel adapter formats for its medium.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger("router")


@dataclass
class CommandResult:
    """Result from processing a command."""
    text: str
    approval_id: Optional[str] = None  # If an approval item was created
    items: Optional[list] = None       # For list-type responses


class CommandRouter:
    """Routes text commands to handlers. Channel-agnostic."""

    def __init__(self, store, cost_tracker, policy_engine, call_llm_fn):
        self.store = store
        self.cost_tracker = cost_tracker
        self.policy = policy_engine
        self.call_llm = call_llm_fn

    def route(self, text: str, username: str = "bob") -> CommandResult:
        """Parse and execute a command. Returns a CommandResult."""
        text = text.strip()
        text_lower = text.lower()

        # Draft
        if text_lower.startswith("draft ") or text_lower.startswith("write "):
            topic = text[6:].strip()
            return self._handle_draft(topic)

        # Classify
        if text_lower.startswith("classify ") or text_lower.startswith("email "):
            email_text = text[9:].strip() if text_lower.startswith("classify ") else text[6:].strip()
            return self._handle_classify(email_text)

        # Research
        if text_lower.startswith("/research") or text_lower == "research" or (
            "research" in text_lower and "scan" in text_lower
        ):
            return self._handle_research()

        # Costs
        if text_lower.startswith("/costs") or text_lower == "costs":
            return self._handle_costs()

        # Status
        if text_lower.startswith("/status") or text_lower == "status":
            return self._handle_status()

        # Audit
        if text_lower.startswith("/audit") or text_lower == "audit":
            return self._handle_audit()

        # Approve
        if text_lower.startswith("approve "):
            item_id = text[8:].strip()
            return self._handle_approve(item_id, username)

        # Reject
        if text_lower.startswith("reject "):
            item_id = text[7:].strip()
            return self._handle_reject(item_id, username)

        # Pending
        if text_lower in ("pending", "/pending", "queue", "/queue"):
            return self._handle_pending()

        # Help / greeting
        if text_lower in ("hi", "hello", "hey", "start", "/help", "help", "/start"):
            return self._handle_help()

        # Unknown — try as a general question
        return CommandResult(
            text=(
                "🤖 I didn't understand that. Try:\n"
                "• draft about [topic]\n"
                "• classify [email text]\n"
                "• research\n"
                "• costs\n"
                "• status\n"
                "• pending\n"
                "• approve [id]\n"
                "• reject [id]"
            )
        )

    def _handle_draft(self, topic: str) -> CommandResult:
        try:
            result = self.call_llm(
                "personal/writing_agent",
                "Write a LinkedIn post for the AIGovOps Foundation. Practitioner-first voice, no superlatives, no CTAs. 100-150 words.",
                topic,
            )
            item_id = self.store.enqueue_approval(
                agent="personal/writing_agent",
                action_type="linkedin_post",
                description=f"Draft about: {topic}",
                draft_content=result,
            )
            self.store.log_audit(
                agent="personal/writing_agent", action="draft",
                result_summary=f"Drafted about: {topic[:50]}",
            )
            return CommandResult(
                text=f"✍️ Writing Agent draft:\n\n{result}\n\n[Approve: approve {item_id[:8]}] [Reject: reject {item_id[:8]}]",
                approval_id=item_id,
            )
        except Exception as e:
            return CommandResult(text=f"❌ Draft failed: {e}")

    def _handle_classify(self, email_text: str) -> CommandResult:
        try:
            result = self.call_llm(
                "personal/email_classifier",
                'Classify this email. JSON: {"category":"action-required|FYI-only|newsletter|spam|foundation-business","confidence":0.0-1.0,"draft":"brief reply"}',
                email_text, json_mode=True,
            )
            parsed = json.loads(result)
            cat = parsed.get("category", "?")
            conf = int(parsed.get("confidence", 0) * 100)
            draft = parsed.get("draft", "")

            response = f"📧 Email Agent:\n  Category: {cat}\n  Confidence: {conf}%"
            if draft:
                response += f"\n\n  Draft reply: {draft}"

            item_id = None
            if cat == "action-required":
                item_id = self.store.enqueue_approval(
                    agent="personal/email_classifier",
                    action_type="email_reply",
                    description=f"Reply to: {email_text[:80]}",
                    draft_content=draft,
                )
                response += f"\n\n[Approve: approve {item_id[:8]}] [Reject: reject {item_id[:8]}]"
            else:
                response += "\n\nAuto-archived (no action needed)."

            self.store.log_audit(
                agent="personal/email_classifier", action="classify",
                result_summary=f"category={cat}, confidence={conf}%",
            )
            return CommandResult(text=response, approval_id=item_id)
        except Exception as e:
            return CommandResult(text=f"❌ Classification failed: {e}")

    def _handle_research(self) -> CommandResult:
        try:
            result = self.call_llm(
                "personal/research_scanner",
                'Find 3 current AI governance topics. JSON: {"items":[{"title":"...","score":1-5,"summary":"one sentence"}]}',
                "AI governance, responsible AI, AI regulation news this week",
                json_mode=True,
            )
            parsed = json.loads(result)
            items = parsed.get("items", [])
            digest = "📊 Research Digest\n\n"
            for i, item in enumerate(items[:3], 1):
                digest += f"{i}. [{item.get('score',3)}/5] {item.get('title','?')}\n   {item.get('summary','')}\n\n"
            self.store.log_audit(
                agent="personal/research_scanner", action="scan",
                result_summary=f"Found {len(items)} items",
            )
            return CommandResult(text=digest)
        except Exception as e:
            return CommandResult(text=f"❌ Research failed: {e}")

    def _handle_costs(self) -> CommandResult:
        report = self.cost_tracker.get_weekly_report()
        by_agent = "\n".join(
            f"  • {a['agent']}: ${a['cost']:.4f} ({a['calls']} calls)"
            for a in report["by_agent"][:5]
        ) or "  No data yet"

        return CommandResult(text=(
            f"💰 Costs (7 days)\n\n"
            f"Total: ${report['total_cost']:.4f}\n"
            f"Calls: {report['total_calls']}\n"
            f"Cached: {report['cached_calls']} ({report['cache_savings_pct']}% savings)\n\n"
            f"By agent:\n{by_agent}\n\n"
            f"Period: {report['period']}"
        ))

    def _handle_status(self) -> CommandResult:
        pending = self.store.get_pending_approvals()
        report = self.cost_tracker.get_daily_cost()
        return CommandResult(text=(
            f"📊 Status\n\n"
            f"• Bot: ✅ Online (v3)\n"
            f"• OpenAI: ✅\n"
            f"• Pending approvals: {len(pending)}\n"
            f"• Today's cost: ${report['total_cost']:.4f}\n"
            f"• Today's LLM calls: {report['total_calls']}"
        ))

    def _handle_audit(self) -> CommandResult:
        entries = self.store.get_audit_log(limit=10)
        if not entries:
            return CommandResult(text="📋 No audit entries yet.")
        lines = []
        for e in entries[:10]:
            ts = e["timestamp"][:16].replace("T", " ")
            lines.append(f"{ts} | {e['agent']} → {e['action']} [{e['status']}]")
        return CommandResult(text="📋 Recent Audit Log\n\n" + "\n".join(lines))

    def _handle_approve(self, item_id: str, username: str) -> CommandResult:
        # Find item by prefix match
        pending = self.store.get_pending_approvals()
        match = next((p for p in pending if p["id"].startswith(item_id)), None)
        if not match:
            return CommandResult(text=f"❌ No pending item matching '{item_id}'")
        self.store.approve_item(match["id"], username)
        self.store.log_audit(
            agent="system/bot", action="approve", operator=username,
            result_summary=f"Approved {match['id'][:8]}",
        )
        return CommandResult(text=f"✅ Approved: {match['description'][:60]}")

    def _handle_reject(self, item_id: str, username: str) -> CommandResult:
        pending = self.store.get_pending_approvals()
        match = next((p for p in pending if p["id"].startswith(item_id)), None)
        if not match:
            return CommandResult(text=f"❌ No pending item matching '{item_id}'")
        self.store.reject_item(match["id"], username)
        self.store.log_audit(
            agent="system/bot", action="reject", operator=username,
            result_summary=f"Rejected {match['id'][:8]}",
        )
        return CommandResult(text=f"❌ Rejected: {match['description'][:60]}")

    def _handle_pending(self) -> CommandResult:
        pending = self.store.get_pending_approvals()
        if not pending:
            return CommandResult(text="✅ No pending approvals. All clear.")
        lines = [f"📋 Pending approvals ({len(pending)}):\n"]
        for p in pending[:10]:
            lines.append(f"  • [{p['id'][:8]}] {p['description'][:50]}")
        return CommandResult(text="\n".join(lines), items=pending)

    def _handle_help(self) -> CommandResult:
        return CommandResult(text=(
            "🤖 AIGovOps Bot v3\n\n"
            "Commands:\n"
            "• draft about [topic] — AI drafts content\n"
            "• classify [email text] — classify an email\n"
            "• research — AI governance news\n"
            "• costs — 7-day cost report\n"
            "• status — system health\n"
            "• audit — recent actions\n"
            "• pending — show approval queue\n"
            "• approve [id] — approve an item\n"
            "• reject [id] — reject an item\n"
            "• help — this message"
        ))
