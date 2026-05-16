"""Notification dispatcher — routes messages to all configured channels.

Handles channel preferences per operator and urgency-based routing:
- Critical: ALL channels (Telegram + WhatsApp + SMS + Web + Voice)
- High: Telegram + WhatsApp + Web
- Normal: Telegram + Web
- Low: Web only (batch into digest)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.personal_foundation.v2.channels import ChannelAdapter, ChannelMessage
from src.personal_foundation.v2.state import StateStore

log = logging.getLogger(__name__)

# Default routing rules per urgency level
URGENCY_ROUTING = {
    "critical": ["telegram", "whatsapp", "sms", "web", "voice"],
    "high": ["telegram", "whatsapp", "web"],
    "normal": ["telegram", "web"],
    "low": ["web"],
}


class NotificationDispatcher:
    """Routes notifications to appropriate channels based on urgency and preferences."""

    def __init__(self, store: StateStore) -> None:
        self.store = store
        self._channels: dict[str, ChannelAdapter] = {}
        # Operator channel preferences (can be overridden via config)
        self._preferences: dict[str, list[str]] = {
            "bob": ["telegram", "whatsapp", "web", "sms", "voice"],
            "ken": ["telegram", "web"],
        }

    def register_channel(self, channel: ChannelAdapter) -> None:
        """Register a channel adapter."""
        self._channels[channel.channel_name] = channel
        log.info("Dispatcher: registered channel '%s'", channel.channel_name)

    def set_preferences(self, operator: str, channels: list[str]) -> None:
        """Set channel preferences for an operator."""
        self._preferences[operator] = channels

    async def notify(self, recipient: str, text: str, urgency: str = "normal", item_id: str = "") -> dict[str, bool]:
        """Send a notification to an operator via appropriate channels.

        Returns: {channel_name: success} for each attempted channel.
        """
        # Determine which channels to use
        urgency_channels = URGENCY_ROUTING.get(urgency, ["web"])
        operator_channels = self._preferences.get(recipient, ["telegram", "web"])
        target_channels = [c for c in urgency_channels if c in operator_channels]

        if not target_channels:
            target_channels = ["web"]  # Always at least web

        results = {}
        message = ChannelMessage(
            recipient=recipient, text=text, urgency=urgency, item_id=item_id,
        )

        tasks = []
        for channel_name in target_channels:
            adapter = self._channels.get(channel_name)
            if adapter:
                tasks.append((channel_name, adapter.send(message)))

        for channel_name, coro in tasks:
            try:
                results[channel_name] = await coro
            except Exception as exc:
                log.error("Dispatcher: %s failed: %s", channel_name, exc)
                results[channel_name] = False

        return results

    async def send_approval_request(self, item: dict) -> dict[str, bool]:
        """Send an approval request to all configured channels for the approval operator."""
        results = {}
        # Approval requests go to all channels that support buttons
        for channel_name in ["telegram", "whatsapp", "web"]:
            adapter = self._channels.get(channel_name)
            if adapter:
                try:
                    results[channel_name] = await adapter.send_approval_request(item)
                except Exception as exc:
                    log.error("Dispatcher: approval via %s failed: %s", channel_name, exc)
                    results[channel_name] = False
        return results

    async def broadcast(self, text: str, urgency: str = "normal") -> None:
        """Send to all operators via their preferred channels."""
        for operator in self._preferences:
            await self.notify(operator, text, urgency)

    async def start_all(self) -> None:
        """Start all channel adapters that have listeners."""
        for name, adapter in self._channels.items():
            try:
                await adapter.start()
                log.info("Dispatcher: started %s", name)
            except Exception as exc:
                log.error("Dispatcher: failed to start %s: %s", name, exc)

    async def stop_all(self) -> None:
        """Stop all channel adapters."""
        for name, adapter in self._channels.items():
            try:
                await adapter.stop()
            except Exception:
                pass
