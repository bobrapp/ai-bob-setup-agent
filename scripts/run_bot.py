#!/usr/bin/env python3
"""AIGovOps Bot — Telegram interface to the v2 agent engine.

This is the single entry point. It:
- Runs the Telegram bot (commands + approve/reject buttons)
- Polls Gmail every 5 min and classifies emails
- Uses the v2 engine: PolicyEngine, CostTracker, StateStore, EventBus
- Serves a health endpoint on :8000 for Fly.io

Run: python3 scripts/run_bot.py
"""

import asyncio
import json
import logging
import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler,
    MessageHandler, ContextTypes, filters,
)

from src.personal_foundation.v2.state import StateStore
from src.personal_foundation.v2.cost_tracker import CostTracker
from src.personal_foundation.v2.policy import PolicyEngine, PolicyContext

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("bot")

# ─── Config ────────────────────────────────────────────────────────────────────

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
BOB_CHAT_ID = os.getenv("TELEGRAM_BOB_CHAT_ID", "")
KEN_CHAT_ID = os.getenv("TELEGRAM_KEN_CHAT_ID", "")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
EMAIL_POLLING_ENABLED = os.getenv("EMAIL_POLLING_ENABLED", "true").lower() == "true"

ALLOWED_CHAT_IDS = set()
if BOB_CHAT_ID:
    ALLOWED_CHAT_IDS.add(int(BOB_CHAT_ID))
if KEN_CHAT_ID:
    ALLOWED_CHAT_IDS.add(int(KEN_CHAT_ID))

# ─── Core services (initialized once) ─────────────────────────────────────────

store = StateStore()
cost_tracker = CostTracker(store)
policy_engine = PolicyEngine()


# ─── Health server ─────────────────────────────────────────────────────────────

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        pending = len(store.get_pending_approvals())
        body = json.dumps({
            "status": "ok", "version": "3.0",
            "email_polling": EMAIL_POLLING_ENABLED,
            "pending_approvals": pending,
        })
        self.wfile.write(body.encode())

    def log_message(self, format, *args):
        pass


def start_health_server():
    HTTPServer(("0.0.0.0", 8000), HealthHandler).serve_forever()


# ─── LLM call (with cost tracking) ────────────────────────────────────────────

def call_llm(agent_name: str, system: str, user: str, json_mode: bool = False) -> str:
    """Call OpenAI and track cost via the v2 CostTracker."""
    import urllib.request

    if not OPENAI_KEY:
        return '{"error": "OPENAI_API_KEY not set"}'

    body = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": 500,
        "temperature": 0.3,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    data = json.dumps(body).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=data,
        headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=30)
    result = json.loads(resp.read())

    # Track cost
    usage = result.get("usage", {})
    cost_tracker.record(
        agent=agent_name,
        model="gpt-4o-mini",
        input_tokens=usage.get("prompt_tokens", 0),
        output_tokens=usage.get("completion_tokens", 0),
    )

    return result["choices"][0]["message"]["content"]


# ─── Handlers ──────────────────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle approve/reject/edit button taps."""
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    parts = data.split(":", 1)
    if len(parts) != 2:
        return

    action, item_id = parts
    user = query.from_user.first_name or "Unknown"
    username = "bob" if str(query.from_user.id) == BOB_CHAT_ID else "ken"

    # Policy check
    ctx = PolicyContext(
        principal=username, action=action,
        resource_type="approval_item", resource_id=item_id, attributes={},
    )
    decision = policy_engine.evaluate(ctx)
    if not decision.permitted:
        await query.edit_message_text(f"⛔ Policy denied: {decision.reason}")
        return

    if action == "approve":
        store.approve_item(item_id, username)
        await query.edit_message_text(f"✅ *Approved* by {user}", parse_mode="Markdown")
        store.log_audit(agent="system/bot", action="approve", operator=username,
                       result_summary=f"Approved {item_id}")
    elif action == "reject":
        store.reject_item(item_id, username)
        await query.edit_message_text(f"❌ *Rejected* by {user}", parse_mode="Markdown")
        store.log_audit(agent="system/bot", action="reject", operator=username,
                       result_summary=f"Rejected {item_id}")
    elif action == "edit":
        await query.edit_message_text(
            f"✏️ *Edit mode* for `{item_id}`\n\nReply with your edited content.",
            parse_mode="Markdown",
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle natural language messages."""
    if not update.message or not update.message.text:
        return

    chat_id = update.message.chat_id
    if ALLOWED_CHAT_IDS and chat_id not in ALLOWED_CHAT_IDS:
        await update.message.reply_text("⛔ Access denied.")
        return

    text = update.message.text.strip()
    text_lower = text.lower()

    # Draft content
    if text_lower.startswith("draft ") or text_lower.startswith("write "):
        topic = text[6:].strip()
        await update.message.reply_text(f"✍️ Drafting: _{topic}_...", parse_mode="Markdown")
        try:
            result = call_llm(
                "personal/writing_agent",
                "Write a LinkedIn post for the AIGovOps Foundation. Practitioner-first voice, no superlatives, no CTAs. 100-150 words.",
                topic,
            )
            # Create approval item
            item_id = store.enqueue_approval(
                agent="personal/writing_agent",
                action_type="linkedin_post",
                description=f"Draft about: {topic}",
                draft_content=result,
            )
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Approve", callback_data=f"approve:{item_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject:{item_id}"),
                InlineKeyboardButton("✏️ Edit", callback_data=f"edit:{item_id}"),
            ]])
            await update.message.reply_text(
                f"*Writing Agent:*\n\n{result}", parse_mode="Markdown", reply_markup=keyboard,
            )
            store.log_audit(agent="personal/writing_agent", action="draft",
                          result_summary=f"Drafted about: {topic[:50]}")
        except Exception as e:
            await update.message.reply_text(f"❌ Draft failed: {e}")
        return

    # Classify email
    if text_lower.startswith("classify ") or text_lower.startswith("email "):
        email_text = text[9:].strip() if text_lower.startswith("classify ") else text[6:].strip()
        await update.message.reply_text("📧 Classifying...")
        try:
            result = call_llm(
                "personal/email_classifier",
                'Classify this email. JSON: {"category":"action-required|FYI-only|newsletter|spam|foundation-business","confidence":0.0-1.0,"draft":"brief reply"}',
                email_text, json_mode=True,
            )
            parsed = json.loads(result)
            cat = parsed.get("category", "?")
            conf = int(parsed.get("confidence", 0) * 100)
            draft = parsed.get("draft", "")

            response = f"*Email Agent:*\n  Category: `{cat}`\n  Confidence: {conf}%"
            if draft:
                response += f"\n\n*Draft reply:*\n{draft}"

            if cat == "action-required":
                item_id = store.enqueue_approval(
                    agent="personal/email_classifier",
                    action_type="email_reply",
                    description=f"Reply to: {email_text[:80]}",
                    draft_content=draft,
                )
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Send", callback_data=f"approve:{item_id}"),
                    InlineKeyboardButton("❌ Discard", callback_data=f"reject:{item_id}"),
                ]])
                await update.message.reply_text(response, parse_mode="Markdown", reply_markup=keyboard)
            else:
                await update.message.reply_text(response + "\n\n_Auto-archived_", parse_mode="Markdown")

            store.log_audit(agent="personal/email_classifier", action="classify",
                          result_summary=f"category={cat}, confidence={conf}%")
        except Exception as e:
            await update.message.reply_text(f"❌ Classification failed: {e}")
        return

    # Research scan
    if text_lower.startswith("/research") or ("research" in text_lower and "scan" in text_lower):
        await update.message.reply_text("🔬 Scanning...")
        try:
            result = call_llm(
                "personal/research_scanner",
                'Find 3 current AI governance topics. JSON: {"items":[{"title":"...","score":1-5,"summary":"one sentence"}]}',
                "AI governance, responsible AI, AI regulation news this week",
                json_mode=True,
            )
            parsed = json.loads(result)
            items = parsed.get("items", [])
            digest = "*📊 Research Digest*\n\n"
            for i, item in enumerate(items[:3], 1):
                digest += f"{i}. [{item.get('score',3)}/5] *{item.get('title','?')}*\n   {item.get('summary','')}\n\n"
            await update.message.reply_text(digest, parse_mode="Markdown")
            store.log_audit(agent="personal/research_scanner", action="scan",
                          result_summary=f"Found {len(items)} items")
        except Exception as e:
            await update.message.reply_text(f"❌ Research failed: {e}")
        return

    # Default help
    if text_lower in ("hi", "hello", "hey", "start"):
        await update.message.reply_text(
            "🤖 *AIGovOps Bot v3*\n\n"
            "• `draft about [topic]`\n"
            "• `classify [email text]`\n"
            "• `/research` — AI governance news\n"
            "• `/costs` — running costs\n"
            "• `/status` — system health\n"
            "• `/audit` — recent actions\n",
            parse_mode="Markdown",
        )


# ─── Commands ──────────────────────────────────────────────────────────────────

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pending = store.get_pending_approvals()
    report = cost_tracker.get_daily_cost()
    polling = "✅ Active" if EMAIL_POLLING_ENABLED else "⏸️ Off"

    await update.message.reply_text(
        "📊 *Status*\n\n"
        f"• Bot: ✅ Online (v3)\n"
        f"• OpenAI: {'✅' if OPENAI_KEY else '❌'}\n"
        f"• Email polling: {polling}\n"
        f"• Pending approvals: {len(pending)}\n"
        f"• Today's cost: `${report['total_cost']:.4f}`\n"
        f"• Today's LLM calls: {report['total_calls']}\n",
        parse_mode="Markdown",
    )


async def cmd_costs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    report = cost_tracker.get_weekly_report()
    by_agent = "\n".join(
        f"  • {a['agent']}: `${a['cost']:.4f}` ({a['calls']} calls)"
        for a in report["by_agent"][:5]
    ) or "  No data yet"

    await update.message.reply_text(
        f"💰 *Costs (7 days)*\n\n"
        f"Total: `${report['total_cost']:.4f}`\n"
        f"Calls: {report['total_calls']}\n"
        f"Cached: {report['cached_calls']} ({report['cache_savings_pct']}% savings)\n\n"
        f"*By agent:*\n{by_agent}\n\n"
        f"_Period: {report['period']}_",
        parse_mode="Markdown",
    )


async def cmd_audit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entries = store.get_audit_log(limit=10)
    if not entries:
        await update.message.reply_text("📋 No audit entries yet.")
        return

    lines = []
    for e in entries[:10]:
        ts = e["timestamp"][:16].replace("T", " ")
        lines.append(f"`{ts}` {e['agent']} → {e['action']} [{e['status']}]")

    await update.message.reply_text(
        "*📋 Recent Audit Log*\n\n" + "\n".join(lines),
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 *AIGovOps Bot v3*\n\n"
        "*Commands:*\n"
        "• `draft about [topic]` — AI drafts content\n"
        "• `classify [email text]` — classify an email\n"
        "• `/research` — AI governance news\n"
        "• `/costs` — 7-day cost report\n"
        "• `/status` — system health\n"
        "• `/audit` — recent actions\n"
        "• `/help` — this message\n\n"
        "*Buttons:* Tap ✅ ❌ ✏️ on approval items",
        parse_mode="Markdown",
    )


# ─── Email polling ─────────────────────────────────────────────────────────────

async def start_email_polling(app: Application) -> None:
    """Start email polling as a background task."""
    if not EMAIL_POLLING_ENABLED:
        log.info("Email polling disabled")
        return
    from scripts.email_poller import poll_loop
    log.info("Starting email polling (5 min interval)...")
    asyncio.create_task(poll_loop())


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    threading.Thread(target=start_health_server, daemon=True).start()
    log.info("Health server on :8000")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("costs", cmd_costs))
    app.add_handler(CommandHandler("audit", cmd_audit))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("research", handle_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.post_init = start_email_polling

    # Log startup to audit trail
    store.log_audit(agent="system/bot", action="startup",
                   result_summary=f"Bot v3 started. Polling={EMAIL_POLLING_ENABLED}")

    log.info("Bot v3 started. Agents: policy engine + cost tracker + audit trail active.")
    app.run_polling()


if __name__ == "__main__":
    main()
