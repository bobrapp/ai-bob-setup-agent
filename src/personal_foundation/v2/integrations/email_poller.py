"""IMAP email poller — connects to Gmail/Superhuman and emits email.arrived events.

Polls every 60 seconds for new unread emails. Emits event with sender, subject, preview.
Never stores email bodies — only metadata for classification.
"""

from __future__ import annotations

import asyncio
import email
import imaplib
import logging
import os
from datetime import datetime, timezone
from email.header import decode_header
from typing import Any

from src.personal_foundation.v2.state import StateStore

log = logging.getLogger(__name__)


class EmailPoller:
    """IMAP poller that emits email.arrived events."""

    def __init__(self, store: StateStore, poll_interval: int = 60) -> None:
        self.store = store
        self.poll_interval = poll_interval
        self._imap_host = os.getenv("IMAP_HOST", "imap.gmail.com")
        self._imap_port = int(os.getenv("IMAP_PORT", "993"))
        self._imap_user = os.getenv("IMAP_USER", "")
        self._imap_password = os.getenv("IMAP_PASSWORD", "")  # App password for Gmail
        self._running = False
        self._seen_ids: set[str] = set()

    @property
    def is_configured(self) -> bool:
        return bool(self._imap_user and self._imap_password)

    async def start(self) -> None:
        """Start polling for new emails."""
        if not self.is_configured:
            log.warning("EmailPoller: IMAP credentials not configured (IMAP_USER, IMAP_PASSWORD)")
            return

        self._running = True
        log.info("EmailPoller: started (host=%s, user=%s, interval=%ds)",
                 self._imap_host, self._imap_user, self.poll_interval)

        while self._running:
            try:
                await self._poll()
            except Exception as exc:
                log.error("EmailPoller: poll failed: %s", exc)
                self.store.log_audit(
                    agent="system/email_poller", action="poll_failed",
                    status="failure", result_summary=f"IMAP poll error: {type(exc).__name__}",
                )
            await asyncio.sleep(self.poll_interval)

    def stop(self) -> None:
        self._running = False
        log.info("EmailPoller: stopped")

    async def _poll(self) -> None:
        """Connect to IMAP, fetch unread emails, emit events."""
        # Run IMAP in thread pool (it's blocking I/O)
        loop = asyncio.get_event_loop()
        new_emails = await loop.run_in_executor(None, self._fetch_unread)

        for email_data in new_emails:
            msg_id = email_data.get("message_id", "")
            if msg_id in self._seen_ids:
                continue
            self._seen_ids.add(msg_id)

            # Emit event (metadata only — never the body)
            self.store.emit_event("email.arrived", {
                "message_id": msg_id,
                "sender": email_data.get("sender", ""),
                "subject": email_data.get("subject", ""),
                "preview": email_data.get("preview", "")[:500],  # First 500 chars only
                "received_at": email_data.get("date", datetime.now(timezone.utc).isoformat()),
            })

        if new_emails:
            log.info("EmailPoller: %d new emails detected", len(new_emails))

    def _fetch_unread(self) -> list[dict[str, str]]:
        """Fetch unread emails via IMAP. Returns list of metadata dicts."""
        results = []
        try:
            conn = imaplib.IMAP4_SSL(self._imap_host, self._imap_port)
            conn.login(self._imap_user, self._imap_password)
            conn.select("INBOX")

            # Search for unseen messages
            status, data = conn.search(None, "UNSEEN")
            if status != "OK" or not data[0]:
                conn.logout()
                return []

            msg_ids = data[0].split()[-20:]  # Last 20 unread max per poll

            for msg_id in msg_ids:
                status, msg_data = conn.fetch(msg_id, "(RFC822.HEADER BODY.PEEK[TEXT])")
                if status != "OK":
                    continue

                # Parse headers
                raw_headers = msg_data[0][1] if msg_data[0] else b""
                msg = email.message_from_bytes(raw_headers)

                sender = self._decode_header(msg.get("From", ""))
                subject = self._decode_header(msg.get("Subject", ""))
                message_id = msg.get("Message-ID", str(msg_id))
                date = msg.get("Date", "")

                # Get preview (first part of body)
                preview = ""
                if len(msg_data) > 1 and msg_data[1]:
                    body_bytes = msg_data[1][1] if isinstance(msg_data[1], tuple) else b""
                    try:
                        preview = body_bytes.decode("utf-8", errors="ignore")[:500]
                    except Exception:
                        preview = ""

                results.append({
                    "message_id": message_id,
                    "sender": sender,
                    "subject": subject,
                    "preview": preview,
                    "date": date,
                })

            conn.logout()
        except Exception as exc:
            log.error("EmailPoller: IMAP fetch error: %s", exc)

        return results

    def _decode_header(self, value: str) -> str:
        """Decode an email header value."""
        try:
            parts = decode_header(value)
            decoded = []
            for part, charset in parts:
                if isinstance(part, bytes):
                    decoded.append(part.decode(charset or "utf-8", errors="ignore"))
                else:
                    decoded.append(part)
            return " ".join(decoded)
        except Exception:
            return value
