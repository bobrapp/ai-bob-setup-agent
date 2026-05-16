"""WhatsApp channel adapter — via Meta Cloud API or Twilio.

Supports:
- Approval notifications with quick-reply buttons
- Status queries
- Agent control commands
"""

from __future__ import annotations

import logging
import os

import httpx

from src.personal_foundation.v2.channels import ChannelAdapter, ChannelMessage

log = logging.getLogger(__name__)

# Meta Cloud API (WhatsApp Business)
WHATSAPP_API_URL = "https://graph.facebook.com/v18.0"


class WhatsAppChannel(ChannelAdapter):
    """WhatsApp via Meta Cloud API (or Twilio as fallback)."""

    channel_name = "whatsapp"

    def __init__(self, phone_numbers: dict[str, str], provider: str = "meta") -> None:
        """
        Args:
            phone_numbers: {"bob": "+1234567890", "ken": "+0987654321"}
            provider: "meta" (Cloud API) or "twilio"
        """
        self.phone_numbers = phone_numbers
        self.provider = provider
        self._token = os.getenv("WHATSAPP_TOKEN", "")
        self._phone_id = os.getenv("WHATSAPP_PHONE_ID", "")
        self._client = httpx.AsyncClient(timeout=30)

    async def send(self, message: ChannelMessage) -> bool:
        phone = self.phone_numbers.get(message.recipient)
        if not phone:
            log.warning("WhatsAppChannel: no phone for %s", message.recipient)
            return False

        if self.provider == "meta":
            return await self._send_meta(phone, message)
        else:
            return await self._send_twilio(phone, message)

    async def send_approval_request(self, item: dict) -> bool:
        text = (
            f"🔔 *Approval Required*\n\n"
            f"Agent: {item.get('agent', '')}\n"
            f"Action: {item.get('action_type', '')}\n"
            f"Description: {item.get('description', '')}\n\n"
            f"Reply:\n"
            f"  ✅ APPROVE {item['id'][:8]}\n"
            f"  ❌ REJECT {item['id'][:8]}\n"
            f"  ✏️ EDIT {item['id'][:8]}"
        )
        msg = ChannelMessage(recipient="bob", text=text, urgency="high")
        return await self.send(msg)

    async def send_notification(self, recipient: str, text: str, urgency: str = "normal") -> bool:
        msg = ChannelMessage(recipient=recipient, text=text, urgency=urgency)
        return await self.send(msg)

    async def _send_meta(self, phone: str, message: ChannelMessage) -> bool:
        """Send via Meta WhatsApp Cloud API."""
        if not self._token or not self._phone_id:
            log.warning("WhatsAppChannel: WHATSAPP_TOKEN or WHATSAPP_PHONE_ID not set")
            return False

        try:
            resp = await self._client.post(
                f"{WHATSAPP_API_URL}/{self._phone_id}/messages",
                headers={"Authorization": f"Bearer {self._token}"},
                json={
                    "messaging_product": "whatsapp",
                    "to": phone,
                    "type": "text",
                    "text": {"body": message.text},
                },
            )
            return resp.status_code == 200
        except Exception as exc:
            log.error("WhatsAppChannel: send failed: %s", exc)
            return False

    async def _send_twilio(self, phone: str, message: ChannelMessage) -> bool:
        """Send via Twilio WhatsApp API."""
        account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
        from_number = os.getenv("TWILIO_WHATSAPP_FROM", "")

        if not all([account_sid, auth_token, from_number]):
            log.warning("WhatsAppChannel: Twilio credentials not set")
            return False

        try:
            resp = await self._client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json",
                auth=(account_sid, auth_token),
                data={
                    "From": f"whatsapp:{from_number}",
                    "To": f"whatsapp:{phone}",
                    "Body": message.text,
                },
            )
            return resp.status_code in (200, 201)
        except Exception as exc:
            log.error("WhatsAppChannel: Twilio send failed: %s", exc)
            return False
