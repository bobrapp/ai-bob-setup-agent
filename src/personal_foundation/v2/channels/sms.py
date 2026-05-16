"""SMS channel adapter — via Twilio.

For critical alerts and simple approve/reject via text reply.
"""

from __future__ import annotations

import logging
import os

import httpx

from src.personal_foundation.v2.channels import ChannelAdapter, ChannelMessage

log = logging.getLogger(__name__)


class SMSChannel(ChannelAdapter):
    """SMS via Twilio. Best for critical alerts."""

    channel_name = "sms"

    def __init__(self, phone_numbers: dict[str, str]) -> None:
        self.phone_numbers = phone_numbers  # {"bob": "+1234567890"}
        self._account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
        self._auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
        self._from_number = os.getenv("TWILIO_SMS_FROM", "")
        self._client = httpx.AsyncClient(timeout=30)

    async def send(self, message: ChannelMessage) -> bool:
        phone = self.phone_numbers.get(message.recipient)
        if not phone:
            return False
        return await self._send_sms(phone, message.text[:1600])  # SMS limit

    async def send_approval_request(self, item: dict) -> bool:
        text = (
            f"AIGovOps: {item.get('agent', '')} needs approval.\n"
            f"{item.get('description', '')[:100]}\n"
            f"Reply APPROVE or REJECT"
        )
        return await self.send(ChannelMessage(recipient="bob", text=text, urgency="high"))

    async def send_notification(self, recipient: str, text: str, urgency: str = "normal") -> bool:
        # Only send SMS for critical/high urgency
        if urgency not in ("critical", "high"):
            return True  # Skip low-urgency SMS
        return await self.send(ChannelMessage(recipient=recipient, text=text[:1600]))

    async def _send_sms(self, to: str, body: str) -> bool:
        if not all([self._account_sid, self._auth_token, self._from_number]):
            log.warning("SMSChannel: Twilio credentials not set")
            return False
        try:
            resp = await self._client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{self._account_sid}/Messages.json",
                auth=(self._account_sid, self._auth_token),
                data={"From": self._from_number, "To": to, "Body": body},
            )
            return resp.status_code in (200, 201)
        except Exception as exc:
            log.error("SMSChannel: send failed: %s", exc)
            return False
