"""Voice channel adapter — Siri Shortcuts and Alexa Skills.

Command-based (not conversational). Five supported commands:
1. "What's pending?" → reads queue summary
2. "Approve all low-risk" → batch approve
3. "Suspend [agent]" → suspend
4. "What did my agents do today?" → daily summary
5. "Draft a post about [topic]" → trigger writing agent

Voice commands hit the /api/voice endpoint. This adapter handles
the response formatting for speech output.
"""

from __future__ import annotations

import logging

from src.personal_foundation.v2.channels import ChannelAdapter, ChannelMessage

log = logging.getLogger(__name__)


class VoiceChannel(ChannelAdapter):
    """Voice interface via Siri Shortcuts / Alexa Skills.

    This is a response-only channel — voice commands come in via the API,
    and this adapter formats responses for speech synthesis.
    """

    channel_name = "voice"

    async def send(self, message: ChannelMessage) -> bool:
        # Voice doesn't "send" — it responds to API calls
        # This is a no-op; the API endpoint returns speech text directly
        log.debug("VoiceChannel: would speak: %s", message.text[:100])
        return True

    async def send_approval_request(self, item: dict) -> bool:
        # Voice gets a spoken summary, not buttons
        log.debug("VoiceChannel: approval request for %s", item.get("id", ""))
        return True

    async def send_notification(self, recipient: str, text: str, urgency: str = "normal") -> bool:
        # Critical notifications could trigger a Siri announcement
        if urgency == "critical":
            log.info("VoiceChannel: CRITICAL notification for %s: %s", recipient, text[:100])
        return True

    @staticmethod
    def format_for_speech(text: str) -> str:
        """Clean text for speech synthesis (remove markdown, URLs, etc.)."""
        import re
        # Remove markdown formatting
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'`(.+?)`', r'\1', text)
        # Remove URLs
        text = re.sub(r'https?://\S+', '', text)
        # Remove emoji (keep for now, Siri handles them)
        return text.strip()
