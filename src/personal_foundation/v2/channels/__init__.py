"""Multi-channel interface adapters.

Each channel is a first-class citizen:
- Telegram (inline keyboards, commands)
- WhatsApp (via Twilio or Meta Cloud API)
- SMS (via Twilio)
- Web (via WebSocket push)
- Mobile (via WebSocket push — same as web, PWA)
- Voice (via API — Siri Shortcuts, Alexa Skills)
- Email (via SMTP — digest delivery)

All channels implement the same ChannelAdapter interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ChannelMessage:
    """A message to be delivered via any channel."""
    recipient: str          # Operator name (bob, ken) or "all"
    text: str               # Plain text content
    rich_text: str = ""     # Markdown/HTML for channels that support it
    buttons: list[dict] = None  # [{label, callback_data}] for interactive channels
    urgency: str = "normal"  # low, normal, high, critical
    item_id: str = ""       # Approval item ID (for action buttons)

    def __post_init__(self):
        if self.buttons is None:
            self.buttons = []


@dataclass
class ChannelResponse:
    """A response received from a channel (user action)."""
    channel: str            # telegram, whatsapp, sms, web, voice
    operator: str           # bob, ken
    action: str             # approve, reject, edit, command
    item_id: str = ""       # Which approval item
    content: str = ""       # Edit content or command text
    raw: dict = None        # Raw channel-specific data

    def __post_init__(self):
        if self.raw is None:
            self.raw = {}


class ChannelAdapter(ABC):
    """Base class for all channel adapters."""

    channel_name: str = "unknown"

    @abstractmethod
    async def send(self, message: ChannelMessage) -> bool:
        """Send a message. Returns True on success."""
        ...

    @abstractmethod
    async def send_approval_request(self, item: dict) -> bool:
        """Send an approval request with action buttons."""
        ...

    @abstractmethod
    async def send_notification(self, recipient: str, text: str, urgency: str = "normal") -> bool:
        """Send a simple notification."""
        ...

    async def start(self) -> None:
        """Start listening for incoming messages (if applicable)."""
        pass

    async def stop(self) -> None:
        """Stop listening."""
        pass
