"""Web/Mobile channel adapter — via WebSocket push.

Serves both the web PWA and mobile (same PWA on phone).
Real-time updates via WebSocket connection to the API gateway.
"""

from __future__ import annotations

import logging
from typing import Any

from src.personal_foundation.v2.channels import ChannelAdapter, ChannelMessage

log = logging.getLogger(__name__)


class WebChannel(ChannelAdapter):
    """Web/Mobile PWA channel via WebSocket broadcast.

    This adapter doesn't send directly — it emits events that the
    API gateway's WebSocket handler broadcasts to connected clients.
    """

    channel_name = "web"

    def __init__(self, broadcast_fn=None) -> None:
        """
        Args:
            broadcast_fn: async function that broadcasts to all WebSocket clients.
                         Injected from the API gateway.
        """
        self._broadcast = broadcast_fn

    async def send(self, message: ChannelMessage) -> bool:
        if not self._broadcast:
            log.warning("WebChannel: no broadcast function configured")
            return False
        await self._broadcast({
            "type": "notification",
            "recipient": message.recipient,
            "text": message.text,
            "rich_text": message.rich_text,
            "urgency": message.urgency,
            "buttons": message.buttons,
            "item_id": message.item_id,
        })
        return True

    async def send_approval_request(self, item: dict) -> bool:
        if not self._broadcast:
            return False
        await self._broadcast({
            "type": "approval_request",
            "item": item,
        })
        return True

    async def send_notification(self, recipient: str, text: str, urgency: str = "normal") -> bool:
        return await self.send(ChannelMessage(recipient=recipient, text=text, urgency=urgency))
