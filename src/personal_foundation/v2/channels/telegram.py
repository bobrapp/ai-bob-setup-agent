"""Telegram channel adapter — inline keyboards, commands, notifications."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from src.personal_foundation.v2.channels import ChannelAdapter, ChannelMessage

if TYPE_CHECKING:
    from src.personal_foundation.v2.state import StateStore

log = logging.getLogger(__name__)


class TelegramChannel(ChannelAdapter):
    """Telegram bot with inline approve/reject/edit buttons."""

    channel_name = "telegram"

    def __init__(self, bot_token: str, chat_ids: dict[str, str], store: "StateStore") -> None:
        self.bot_token = bot_token
        self.chat_ids = chat_ids  # {"bob": "123", "ken": "456", "approval": "789"}
        self.store = store
        self._app: Application | None = None

    async def start(self) -> None:
        self._app = Application.builder().token(self.bot_token).build()
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("pending", self._cmd_pending))
        self._app.add_handler(CommandHandler("suspend", self._cmd_suspend))
        self._app.add_handler(CommandHandler("resume", self._cmd_resume))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CallbackQueryHandler(self._handle_callback))
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()
        log.info("TelegramChannel: started polling")

    async def stop(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    async def send(self, message: ChannelMessage) -> bool:
        if not self._app:
            return False
        chat_id = self.chat_ids.get(message.recipient, self.chat_ids.get("approval", ""))
        if not chat_id:
            return False
        try:
            keyboard = None
            if message.buttons:
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton(b["label"], callback_data=b["callback_data"])
                    for b in message.buttons
                ]])
            await self._app.bot.send_message(
                chat_id=chat_id, text=message.text,
                reply_markup=keyboard, parse_mode="Markdown",
            )
            return True
        except Exception as exc:
            log.error("TelegramChannel: send failed: %s", exc)
            return False

    async def send_approval_request(self, item: dict) -> bool:
        msg = ChannelMessage(
            recipient="approval",
            text=(
                f"🔔 *Approval Required*\n\n"
                f"*Agent:* `{item.get('agent', '')}`\n"
                f"*Action:* {item.get('action_type', '')}\n"
                f"*Description:* {item.get('description', '')}\n\n"
                f"*Draft:*\n{item.get('draft_content', '')[:400]}"
            ),
            buttons=[
                {"label": "✅ Approve", "callback_data": f"approve:{item['id']}"},
                {"label": "❌ Reject", "callback_data": f"reject:{item['id']}"},
                {"label": "✏️ Edit", "callback_data": f"edit:{item['id']}"},
            ],
        )
        return await self.send(msg)

    async def send_notification(self, recipient: str, text: str, urgency: str = "normal") -> bool:
        prefix = {"critical": "🚨", "high": "⚠️", "normal": "📋", "low": "ℹ️"}.get(urgency, "📋")
        msg = ChannelMessage(recipient=recipient, text=f"{prefix} {text}")
        return await self.send(msg)

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        data = query.data or ""
        parts = data.split(":", 1)
        if len(parts) != 2:
            return
        action, item_id = parts
        reviewer = query.from_user.username or query.from_user.first_name or "unknown"

        if action == "approve":
            self.store.approve_item(item_id, reviewer)
            self.store.log_audit(agent="system/telegram", action="approve", operator=reviewer,
                               result_summary=f"Approved {item_id}")
            await query.edit_message_text(f"✅ *Approved* by @{reviewer}", parse_mode="Markdown")
        elif action == "reject":
            self.store.reject_item(item_id, reviewer, "Rejected via Telegram")
            self.store.log_audit(agent="system/telegram", action="reject", operator=reviewer,
                               result_summary=f"Rejected {item_id}")
            await query.edit_message_text(f"❌ *Rejected* by @{reviewer}", parse_mode="Markdown")
        elif action == "edit":
            await query.edit_message_text(f"✏️ Reply with edited content for `{item_id}`", parse_mode="Markdown")

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        pending = self.store.get_pending_approvals()
        await update.message.reply_text(
            f"📊 *Status*\nPending: {len(pending)}\nSystem: running",
            parse_mode="Markdown",
        )

    async def _cmd_pending(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        items = self.store.get_pending_approvals()
        if not items:
            await update.message.reply_text("✅ No pending items.")
            return
        lines = [f"📋 *Pending ({len(items)})*\n"]
        for i, item in enumerate(items[:10], 1):
            lines.append(f"{i}. `{item['agent']}` — {item['description'][:50]}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _cmd_suspend(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await update.message.reply_text("Usage: /suspend agent_name")
            return
        agent = context.args[0]
        self.store.suspend_agent(agent, "Telegram command")
        await update.message.reply_text(f"⏸️ `{agent}` suspended.", parse_mode="Markdown")

    async def _cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await update.message.reply_text("Usage: /resume agent_name")
            return
        agent = context.args[0]
        self.store.resume_agent(agent)
        await update.message.reply_text(f"▶️ `{agent}` resumed.", parse_mode="Markdown")

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "🤖 *AIGovOps Automation*\n\n"
            "/status — System health\n"
            "/pending — Approval queue\n"
            "/suspend <agent> — Pause agent\n"
            "/resume <agent> — Resume agent\n"
            "/help — This message",
            parse_mode="Markdown",
        )
