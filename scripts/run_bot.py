#!/usr/bin/env python3
"""Telegram bot — handles button taps + natural language commands + agent workflows.

Run: python3 scripts/run_bot.py

Features:
- Approve/Reject/Edit buttons on approval items
- "draft about [topic]" → Writing Agent drafts content
- "classify [email text]" → Email Agent classifies
- /status, /help, /research commands
- Health endpoint on :8000 for Fly.io
"""

import asyncio
import json
import logging
import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
sys.path.insert(0, '/Users/bobrapp/ai-bob-setup-agent')
# Also support running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("bot")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8719122143:AAH1VPZeJ1vAfd6RRMFTqOI5L0iunjrjKIM")
BOB_CHAT_ID = os.getenv("TELEGRAM_BOB_CHAT_ID", "8668322892")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")

# Only Bob and Ken can use this bot
ALLOWED_CHAT_IDS = {int(BOB_CHAT_ID)} if BOB_CHAT_ID else set()


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"status":"ok","bot":"running","version":"2.0"}')
    def log_message(self, format, *args):
        pass


def start_health_server():
    server = HTTPServer(('0.0.0.0', 8000), HealthHandler)
    server.serve_forever()


def call_openai(system, user, json_mode=False):
    """Call OpenAI API. Returns response text."""
    import urllib.request
    if not OPENAI_KEY:
        return '{"error": "OPENAI_API_KEY not set"}'
    body = {'model': 'gpt-4o-mini', 'messages': [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': user}
    ], 'max_tokens': 500, 'temperature': 0.4}
    if json_mode:
        body['response_format'] = {'type': 'json_object'}
    data = json.dumps(body).encode()
    req = urllib.request.Request('https://api.openai.com/v1/chat/completions',
        data=data, headers={'Authorization': 'Bearer ' + OPENAI_KEY, 'Content-Type': 'application/json'})
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())['choices'][0]['message']['content']


# --- Handlers ---

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    parts = data.split(":", 1)
    if len(parts) != 2:
        return
    action, item_id = parts
    user = query.from_user.first_name or "Unknown"

    if action == "approve":
        await query.edit_message_text(f"✅ *Approved* by {user}\n\nItem `{item_id}` executed.", parse_mode="Markdown")
        log.info("APPROVED: %s by %s", item_id, user)
    elif action == "reject":
        await query.edit_message_text(f"❌ *Rejected* by {user}\n\nItem `{item_id}` discarded.", parse_mode="Markdown")
        log.info("REJECTED: %s by %s", item_id, user)
    elif action == "edit":
        await query.edit_message_text(f"✏️ *Edit mode* for `{item_id}`\n\nReply with your edited content.", parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle natural language messages."""
    if not update.message or not update.message.text:
        return

    # Security: only Bob and Ken
    chat_id = update.message.chat_id
    if ALLOWED_CHAT_IDS and chat_id not in ALLOWED_CHAT_IDS:
        await update.message.reply_text("⛔ Access denied. This bot is for Bob & Ken only.")
        return

    text = update.message.text.strip()
    text_lower = text.lower()

    # Draft content
    if text_lower.startswith("draft ") or text_lower.startswith("write "):
        topic = text[6:].strip() if text_lower.startswith("draft ") else text[6:].strip()
        await update.message.reply_text(f"✍️ Drafting about: _{topic}_...", parse_mode="Markdown")
        try:
            result = call_openai(
                "Write a LinkedIn post for the AIGovOps Foundation. Practitioner-first voice, no superlatives, no CTAs. 100-150 words.",
                topic
            )
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Approve", callback_data="approve:draft_" + str(hash(topic))[:8]),
                InlineKeyboardButton("❌ Reject", callback_data="reject:draft_" + str(hash(topic))[:8]),
                InlineKeyboardButton("✏️ Edit", callback_data="edit:draft_" + str(hash(topic))[:8]),
            ]])
            await update.message.reply_text(f"*Writing Agent draft:*\n\n{result}", parse_mode="Markdown", reply_markup=keyboard)
        except Exception as e:
            await update.message.reply_text(f"❌ Draft failed: {e}")
        return

    # Classify email
    if text_lower.startswith("classify ") or text_lower.startswith("email "):
        email_text = text[9:].strip() if text_lower.startswith("classify ") else text[6:].strip()
        await update.message.reply_text("📧 Classifying...", parse_mode="Markdown")
        try:
            result = call_openai(
                'Classify this email and draft a reply. JSON: {"category":"action-required|FYI-only|newsletter|spam|foundation-business","confidence":0.0-1.0,"draft":"brief reply"}',
                email_text, json_mode=True
            )
            parsed = json.loads(result)
            cat = parsed.get('category', '?')
            conf = int(parsed.get('confidence', 0) * 100)
            draft = parsed.get('draft', '')

            response = f"*Email Agent:*\n  Category: `{cat}`\n  Confidence: {conf}%"
            if draft:
                response += f"\n\n*Draft reply:*\n{draft}"

            if cat == 'action-required':
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Send", callback_data="approve:email_" + str(hash(email_text))[:8]),
                    InlineKeyboardButton("❌ Discard", callback_data="reject:email_" + str(hash(email_text))[:8]),
                ]])
                await update.message.reply_text(response, parse_mode="Markdown", reply_markup=keyboard)
            else:
                await update.message.reply_text(response + "\n\n_Auto-archived (no action needed)_", parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Classification failed: {e}")
        return

    # Research scan
    if text_lower.startswith("/research") or "research" in text_lower and "scan" in text_lower:
        await update.message.reply_text("🔬 Scanning for AI governance research...", parse_mode="Markdown")
        try:
            result = call_openai(
                'Find 3 current AI governance topics. JSON: {"items":[{"title":"...","score":1-5,"summary":"one sentence"}]}',
                'AI governance, responsible AI, AI regulation news and publications from this week',
                json_mode=True
            )
            parsed = json.loads(result)
            items = parsed.get('items', [])
            digest = "*📊 Research Digest*\n\n"
            for i, item in enumerate(items[:3], 1):
                digest += f"{i}. [{item.get('score',3)}/5] *{item.get('title','?')}*\n   {item.get('summary','')}\n\n"
            await update.message.reply_text(digest, parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Research scan failed: {e}")
        return

    # Default: show help
    if text_lower in ('hi', 'hello', 'hey', 'start'):
        await update.message.reply_text(
            "🤖 *AIGovOps Bot — Ready*\n\n"
            "Try these:\n"
            "• `draft about AI governance trends`\n"
            "• `classify From: sarah@corp.com Subject: Partnership inquiry`\n"
            "• `/research` — scan for AI governance news\n"
            "• `/status` — system health\n",
            parse_mode="Markdown"
        )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📊 *System Status*\n\n"
        "• Bot: ✅ Online\n"
        "• OpenAI: " + ("✅" if OPENAI_KEY else "❌") + "\n"
        "• Mode: Production\n"
        "• Agents: 8 configured\n\n"
        "Type `draft about [topic]` to try the Writing Agent.",
        parse_mode="Markdown"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 *AIGovOps Bot*\n\n"
        "*Commands:*\n"
        "• `draft about [topic]` — AI drafts content\n"
        "• `classify [email text]` — classify an email\n"
        "• `/research` — scan AI governance news\n"
        "• `/status` — system health\n"
        "• `/help` — this message\n\n"
        "*On approval items:*\n"
        "Tap ✅ Approve, ❌ Reject, or ✏️ Edit",
        parse_mode="Markdown"
    )


def main():
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    log.info("Health server on :8000")

    token = os.getenv("TELEGRAM_BOT_TOKEN", TOKEN)
    app = Application.builder().token(token).build()
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("research", handle_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Bot started. Listening for messages + button taps...")
    app.run_polling()


if __name__ == "__main__":
    main()


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button taps (approve/reject/edit)."""
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    parts = data.split(":", 1)
    if len(parts) != 2:
        return

    action, item_id = parts
    user = query.from_user.first_name or "Unknown"

    if action == "approve":
        await query.edit_message_text(
            f"✅ *Approved* by {user}\n\nItem `{item_id}` — action will execute.",
            parse_mode="Markdown",
        )
        log.info("APPROVED: %s by %s", item_id, user)

    elif action == "reject":
        await query.edit_message_text(
            f"❌ *Rejected* by {user}\n\nItem `{item_id}` — agent will revise or discard.",
            parse_mode="Markdown",
        )
        log.info("REJECTED: %s by %s", item_id, user)

    elif action == "edit":
        await query.edit_message_text(
            f"✏️ *Edit mode* for `{item_id}`\n\nReply to this message with your edited content.",
            parse_mode="Markdown",
        )
        log.info("EDIT requested: %s by %s", item_id, user)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📊 *AIGovOps Bot Status*\n\n"
        "• System: Online ✅\n"
        "• Mode: Dry-run\n"
        "• Listening for approvals\n\n"
        "Tap buttons on approval items to approve/reject.",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 *AIGovOps Bot*\n\n"
        "I send you approval items with buttons.\n"
        "Tap ✅ to approve, ❌ to reject, ✏️ to edit.\n\n"
        "/status — Check system status\n"
        "/help — This message",
        parse_mode="Markdown",
    )


def main():
    # Start health server in background thread (for Fly.io)
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    log.info("Health server started on :8000")

    import os
    token = os.getenv("TELEGRAM_BOT_TOKEN", TOKEN)

    app = Application.builder().token(token).build()
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("help", cmd_help))

    log.info("Bot started. Listening for button taps...")
    app.run_polling()


if __name__ == "__main__":
    main()
