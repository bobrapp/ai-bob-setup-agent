"""Telegram bot for the Approval Queue and agent control.

INTERNAL USE ONLY.

Provides:
- Inline keyboard buttons for approve / reject / edit on Approval Queue items
- /suspend <agent> and /resume <agent> commands
- /status command showing pending queue + agent health
- Notification delivery for all agents

Run via: make run-foundation
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.personal_foundation.approval_queue import ApprovalItem, ApprovalQueue
from src.personal_foundation.audit_shim import log_action

if TYPE_CHECKING:
    from src.personal_foundation.config import FoundationConfig

log = logging.getLogger(__name__)


class FoundationTelegramBot:
    """Telegram bot that serves as the Approval Queue interface."""

    def __init__(self, config: "FoundationConfig", approval_queue: ApprovalQueue) -> None:
        self.config = config
        self.queue = approval_queue
        self._app: Application | None = None
        self._suspended_agents: set[str] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def build(self) -> Application:
        """Build the Telegram application with all handlers."""
        self._app = (
            Application.builder()
            .token(self.config.telegram.bot_token)
            .build()
        )

        # Commands
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("suspend", self._cmd_suspend))
        self._app.add_handler(CommandHandler("resume", self._cmd_resume))
        self._app.add_handler(CommandHandler("pending", self._cmd_pending))

        # Callback queries (inline button presses)
        self._app.add_handler(CallbackQueryHandler(self._handle_callback))

        return self._app

    async def run(self) -> None:
        """Start polling for updates."""
        app = self.build()
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        log.info("Foundation Telegram bot started. Listening for commands...")

        # Keep running
        try:
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            await app.updater.stop()
            await app.stop()
            await app.shutdown()

    # ------------------------------------------------------------------
    # Present approval items
    # ------------------------------------------------------------------

    async def present_item(self, item: ApprovalItem) -> None:
        """Send an Approval Queue item to the approval channel with inline buttons."""
        if not self._app:
            log.warning("Bot not initialized, cannot present item")
            return

        text = (
            f"🔔 **Approval Required**\n\n"
            f"**Agent:** `{item.agent}`\n"
            f"**Action:** {item.action_type}\n"
            f"**Description:** {item.description}\n\n"
            f"**Draft:**\n{item.draft_content[:500]}"
        )
        if len(item.draft_content) > 500:
            text += "\n\n_(truncated — full content available on approval)_"

        if item.rationale:
            text += f"\n\n**Rationale:** {item.rationale}"

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve:{item.item_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject:{item.item_id}"),
                InlineKeyboardButton("✏️ Edit", callback_data=f"edit:{item.item_id}"),
            ]
        ])

        try:
            await self._app.bot.send_message(
                chat_id=self.config.telegram.approval_chat_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="Markdown",
            )
        except Exception as exc:
            log.error("Failed to present approval item: %s", exc)

    async def send_notification(self, message: str, to_bob: bool = True, to_ken: bool = False) -> bool:
        """Send a notification message to Bob and/or Ken."""
        if not self._app:
            return False

        success = True
        targets = []
        if to_bob:
            targets.append(self.config.telegram.bob_chat_id)
        if to_ken:
            targets.append(self.config.telegram.ken_chat_id)

        for chat_id in targets:
            try:
                await self._app.bot.send_message(chat_id=chat_id, text=message)
            except Exception as exc:
                log.error("Notification failed to %s: %s", chat_id, exc)
                success = False

        return success

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "🤖 AIGovOps Foundation Automation Bot\n\n"
            "Commands:\n"
            "/status — System status\n"
            "/pending — Show pending approval items\n"
            "/suspend <agent> — Suspend an agent\n"
            "/resume <agent> — Resume a suspended agent"
        )

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        pending_count = len(self.queue.pending())
        overdue_count = len(self.queue.overdue())
        suspended = list(self._suspended_agents) or ["none"]

        text = (
            f"📊 **System Status**\n\n"
            f"Pending approvals: {pending_count}\n"
            f"Overdue (>24h): {overdue_count}\n"
            f"Suspended agents: {', '.join(suspended)}\n"
            f"Mode: {'🔒 dry-run' if self.config.dry_run else '🟢 live'}"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    async def _cmd_pending(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        items = self.queue.pending()
        if not items:
            await update.message.reply_text("✅ No pending approval items.")
            return

        lines = [f"📋 **Pending Items ({len(items)})**\n"]
        for i, item in enumerate(items[:10], 1):
            age = (datetime.now(timezone.utc) - item.created_at).total_seconds() / 3600
            lines.append(f"{i}. `{item.agent}` — {item.description[:50]} ({age:.0f}h ago)")

        if len(items) > 10:
            lines.append(f"\n_...and {len(items) - 10} more_")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _cmd_suspend(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await update.message.reply_text("Usage: /suspend <agent_name>\nExample: /suspend personal/email_agent")
            return

        agent_name = context.args[0]
        self._suspended_agents.add(agent_name)

        log_action(
            action="foundation/orchestrator:suspend_agent",
            command=f"/suspend {agent_name}",
            status="success",
            result_summary=f"Agent {agent_name} suspended via Telegram command",
        )

        await update.message.reply_text(f"⏸️ Agent `{agent_name}` suspended.", parse_mode="Markdown")

    async def _cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await update.message.reply_text("Usage: /resume <agent_name>\nExample: /resume personal/email_agent")
            return

        agent_name = context.args[0]
        self._suspended_agents.discard(agent_name)

        log_action(
            action="foundation/orchestrator:resume_agent",
            command=f"/resume {agent_name}",
            status="success",
            result_summary=f"Agent {agent_name} resumed via Telegram command",
        )

        await update.message.reply_text(f"▶️ Agent `{agent_name}` resumed.", parse_mode="Markdown")

    # ------------------------------------------------------------------
    # Callback query handler (inline buttons)
    # ------------------------------------------------------------------

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()

        data = query.data
        if not data:
            return

        parts = data.split(":", 1)
        if len(parts) != 2:
            return

        action, item_id = parts
        reviewer = query.from_user.username or query.from_user.first_name or "unknown"

        if action == "approve":
            await self._handle_approve(query, item_id, reviewer)
        elif action == "reject":
            await self._handle_reject(query, item_id, reviewer)
        elif action == "edit":
            await self._handle_edit_prompt(query, item_id)

    async def _handle_approve(self, query, item_id: str, reviewer: str) -> None:
        try:
            item = self.queue.approve(item_id, reviewer)

            log_action(
                action="foundation/orchestrator:approve",
                command=f"approve item_id={item_id}",
                status="success",
                result_summary=f"Approved by {reviewer}: {item.description[:80]}",
                details={"item_id": item_id, "reviewer": reviewer, "agent": item.agent},
            )

            await query.edit_message_text(
                f"✅ **Approved** by @{reviewer}\n\n"
                f"Agent: `{item.agent}`\n"
                f"Action: {item.action_type}\n"
                f"_{item.description[:80]}_",
                parse_mode="Markdown",
            )
        except (KeyError, ValueError) as exc:
            await query.edit_message_text(f"⚠️ Could not approve: {exc}")

    async def _handle_reject(self, query, item_id: str, reviewer: str) -> None:
        try:
            item = self.queue.reject(item_id, reviewer, reason="Rejected via Telegram")

            log_action(
                action="foundation/orchestrator:reject",
                command=f"reject item_id={item_id}",
                status="success",
                result_summary=f"Rejected by {reviewer}: {item.description[:80]}",
                details={"item_id": item_id, "reviewer": reviewer, "agent": item.agent},
            )

            await query.edit_message_text(
                f"❌ **Rejected** by @{reviewer}\n\n"
                f"Agent: `{item.agent}`\n"
                f"_{item.description[:80]}_",
                parse_mode="Markdown",
            )
        except (KeyError, ValueError) as exc:
            await query.edit_message_text(f"⚠️ Could not reject: {exc}")

    async def _handle_edit_prompt(self, query, item_id: str) -> None:
        await query.edit_message_text(
            f"✏️ **Edit mode** for item `{item_id}`\n\n"
            f"Reply to this message with your edited content. "
            f"The item will be re-queued for final approval.",
            parse_mode="Markdown",
        )

    # ------------------------------------------------------------------
    # Agent suspension check
    # ------------------------------------------------------------------

    def is_suspended(self, agent_name: str) -> bool:
        """Check if an agent is currently suspended."""
        return agent_name in self._suspended_agents
