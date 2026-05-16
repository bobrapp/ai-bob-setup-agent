#!/usr/bin/env python3
"""Minimal Telegram bot listener — handles button taps from approval items.

Run: python3 scripts/run_bot.py

Also serves a health endpoint on port 8000 for Fly.io health checks.
"""

import asyncio
import logging
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
sys.path.insert(0, '/Users/bobrapp/ai-bob-setup-agent')

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("bot")

TOKEN = "8719122143:AAH1VPZeJ1vAfd6RRMFTqOI5L0iunjrjKIM"
BOB_CHAT_ID = "8668322892"


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"status":"ok","bot":"running"}')
    def log_message(self, format, *args):
        pass  # Suppress access logs


def start_health_server():
    """Start a simple HTTP health check server on port 8000."""
    server = HTTPServer(('0.0.0.0', 8000), HealthHandler)
    server.serve_forever()


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
