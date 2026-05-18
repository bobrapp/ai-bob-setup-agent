#!/usr/bin/env python3
"""Automatic email polling — fetches new emails via IMAP, classifies them,
and sends notifications to Telegram.

Can run standalone or be imported into run_bot.py as a background task.

Environment variables:
    IMAP_USER          — Gmail address (bobrapp@gmail.com)
    IMAP_PASSWORD      — Gmail app password
    IMAP_HOST          — IMAP server (default: imap.gmail.com)
    OPENAI_API_KEY     — For classification
    TELEGRAM_BOT_TOKEN — For sending notifications
    TELEGRAM_BOB_CHAT_ID — Bob's chat ID
    EMAIL_POLL_INTERVAL — Seconds between polls (default: 300 = 5 min)
"""

from __future__ import annotations

import asyncio
import email
import email.header
import imaplib
import json
import logging
import os
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

log = logging.getLogger("email_poller")

# ─── Configuration ─────────────────────────────────────────────────────────────

IMAP_USER = os.getenv("IMAP_USER", "bobrapp@gmail.com")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD", "")
IMAP_HOST = os.getenv("IMAP_HOST", "imap.gmail.com")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
BOB_CHAT_ID = os.getenv("TELEGRAM_BOB_CHAT_ID", "8668322892")
POLL_INTERVAL = int(os.getenv("EMAIL_POLL_INTERVAL", "300"))  # 5 minutes

# Track processed emails to avoid duplicates
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SEEN_FILE = DATA_DIR / "seen_emails.json"


@dataclass
class EmailMessage:
    """Parsed email message."""
    uid: str
    from_addr: str
    subject: str
    body: str
    date: Optional[datetime] = None
    to_addr: str = ""
    snippet: str = ""


@dataclass
class ClassificationResult:
    """Result from the email classifier."""
    category: str = "unknown"
    confidence: float = 0.0
    draft: str = ""
    reasoning: str = ""


@dataclass
class PollStats:
    """Statistics for a single poll cycle."""
    fetched: int = 0
    classified: int = 0
    action_required: int = 0
    archived: int = 0
    errors: int = 0
    cost_usd: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ─── Seen-email tracking ──────────────────────────────────────────────────────

def load_seen_uids() -> set:
    """Load set of already-processed email UIDs."""
    if SEEN_FILE.exists():
        try:
            data = json.loads(SEEN_FILE.read_text())
            return set(data.get("uids", []))
        except (json.JSONDecodeError, KeyError):
            pass
    return set()


def save_seen_uids(uids: set) -> None:
    """Persist seen UIDs to disk (keep last 500)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    uid_list = sorted(uids)[-500:]
    SEEN_FILE.write_text(json.dumps({
        "uids": uid_list,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2))


# ─── IMAP fetching ────────────────────────────────────────────────────────────

def decode_header_value(raw: str) -> str:
    """Decode RFC 2047 encoded header values."""
    parts = email.header.decode_header(raw)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return " ".join(decoded)


def extract_body(msg: email.message.Message, max_chars: int = 1000) -> str:
    """Extract plain text body from email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode("utf-8", errors="replace")
                    break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode("utf-8", errors="replace")
    return body[:max_chars].strip()


def fetch_new_emails(max_count: int = 10) -> list[EmailMessage]:
    """Connect to IMAP and fetch unread emails from INBOX."""
    if not IMAP_PASSWORD:
        log.warning("IMAP_PASSWORD not set — skipping email poll")
        return []

    messages = []
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST)
        mail.login(IMAP_USER, IMAP_PASSWORD)
        mail.select("INBOX")

        # Search for unseen messages
        status, data = mail.search(None, "UNSEEN")
        if status != "OK" or not data[0]:
            mail.logout()
            return []

        uids = data[0].split()
        # Process most recent first, limit to max_count
        uids = uids[-max_count:]

        for uid in uids:
            try:
                status, msg_data = mail.fetch(uid, "(RFC822)")
                if status != "OK":
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                from_addr = decode_header_value(msg.get("From", ""))
                subject = decode_header_value(msg.get("Subject", "(no subject)"))
                to_addr = decode_header_value(msg.get("To", ""))
                body = extract_body(msg)

                date = None
                date_str = msg.get("Date")
                if date_str:
                    try:
                        date = parsedate_to_datetime(date_str)
                    except (ValueError, TypeError):
                        pass

                messages.append(EmailMessage(
                    uid=uid.decode() if isinstance(uid, bytes) else str(uid),
                    from_addr=from_addr,
                    subject=subject,
                    body=body,
                    date=date,
                    to_addr=to_addr,
                    snippet=body[:200],
                ))
            except Exception as e:
                log.error("Failed to parse email UID %s: %s", uid, e)

        mail.logout()
    except imaplib.IMAP4.error as e:
        log.error("IMAP connection failed: %s", e)
    except Exception as e:
        log.error("Email fetch error: %s", e)

    return messages


# ─── Classification ────────────────────────────────────────────────────────────

def classify_email(msg: EmailMessage) -> ClassificationResult:
    """Classify an email using OpenAI GPT-4o-mini."""
    if not OPENAI_KEY:
        return ClassificationResult(category="unknown", confidence=0.0)

    system_prompt = (
        "You are an email classifier for Bob Rapp, co-founder of the AIGovOps Foundation. "
        "Classify this email into exactly ONE category:\n"
        "- action-required: needs a reply or action from Bob\n"
        "- FYI-only: informational, no action needed\n"
        "- newsletter: a newsletter or digest email\n"
        "- spam: unsolicited commercial or junk\n"
        "- foundation-business: related to AIGovOps Foundation operations\n\n"
        "Also draft a brief reply if action-required.\n"
        'Respond with JSON: {"category":"...","confidence":0.0-1.0,"draft":"brief reply or empty","reasoning":"one sentence"}'
    )

    user_content = f"From: {msg.from_addr}\nSubject: {msg.subject}\n\n{msg.body[:800]}"

    try:
        body = json.dumps({
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "max_tokens": 300,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }).encode()

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {OPENAI_KEY}",
                "Content-Type": "application/json",
            },
        )
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        content = result["choices"][0]["message"]["content"]
        usage = result.get("usage", {})

        parsed = json.loads(content)
        classification = ClassificationResult(
            category=parsed.get("category", "unknown"),
            confidence=float(parsed.get("confidence", 0.0)),
            draft=parsed.get("draft", ""),
            reasoning=parsed.get("reasoning", ""),
        )

        # Estimate cost: gpt-4o-mini pricing
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        cost = (input_tokens / 1_000_000) * 0.15 + (output_tokens / 1_000_000) * 0.60
        log.info("Classification cost: $%.6f (%d in / %d out tokens)", cost, input_tokens, output_tokens)

        return classification

    except Exception as e:
        log.error("Classification failed: %s", e)
        return ClassificationResult(category="error", confidence=0.0, reasoning=str(e))


# ─── Telegram notifications ───────────────────────────────────────────────────

CATEGORY_EMOJI = {
    "action-required": "🔴",
    "FYI-only": "ℹ️",
    "newsletter": "📰",
    "spam": "🗑️",
    "foundation-business": "🏛️",
    "unknown": "❓",
    "error": "⚠️",
}


def send_telegram_notification(msg: EmailMessage, result: ClassificationResult) -> bool:
    """Send classification result to Bob via Telegram."""
    if not TELEGRAM_TOKEN or not BOB_CHAT_ID:
        log.warning("Telegram not configured — skipping notification")
        return False

    emoji = CATEGORY_EMOJI.get(result.category, "📧")
    confidence_pct = int(result.confidence * 100)

    text = (
        f"{emoji} *Email classified: {result.category}*\n"
        f"Confidence: {confidence_pct}%\n\n"
        f"*From:* {_escape_md(msg.from_addr)}\n"
        f"*Subject:* {_escape_md(msg.subject)}\n"
    )

    if msg.snippet:
        text += f"\n_{_escape_md(msg.snippet[:150])}_\n"

    if result.draft and result.category == "action-required":
        text += f"\n*Draft reply:*\n{_escape_md(result.draft)}\n"

    if result.reasoning:
        text += f"\n_Reason: {_escape_md(result.reasoning)}_"

    try:
        payload = json.dumps({
            "chat_id": BOB_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
        }).encode()

        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status == 200
    except Exception as e:
        log.error("Telegram send failed: %s", e)
        return False


def _escape_md(text: str) -> str:
    """Escape Markdown special characters for Telegram."""
    for ch in ("_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"):
        text = text.replace(ch, f"\\{ch}")
    return text


# ─── Cost log ─────────────────────────────────────────────────────────────────

COST_LOG_FILE = DATA_DIR / "email_poll_costs.json"


def log_poll_cost(stats: PollStats) -> None:
    """Append poll stats to the cost log file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    entries = []
    if COST_LOG_FILE.exists():
        try:
            entries = json.loads(COST_LOG_FILE.read_text())
        except (json.JSONDecodeError, ValueError):
            entries = []

    entries.append({
        "timestamp": stats.timestamp,
        "fetched": stats.fetched,
        "classified": stats.classified,
        "action_required": stats.action_required,
        "archived": stats.archived,
        "errors": stats.errors,
        "cost_usd": round(stats.cost_usd, 6),
    })

    # Keep last 1000 entries
    entries = entries[-1000:]
    COST_LOG_FILE.write_text(json.dumps(entries, indent=2))


# ─── Main poll loop ───────────────────────────────────────────────────────────

def poll_once() -> PollStats:
    """Run a single poll cycle: fetch → classify → notify. Also check for command replies."""
    stats = PollStats()
    seen = load_seen_uids()

    log.info("Polling for new emails...")
    messages = fetch_new_emails(max_count=10)
    stats.fetched = len(messages)

    if not messages:
        log.info("No new emails.")
        return stats

    for msg in messages:
        if msg.uid in seen:
            continue

        # Check if this is a command email (sent TO the bot address)
        if _is_command_email(msg):
            _handle_email_command(msg)
            seen.add(msg.uid)
            continue

        log.info("Classifying: %s — %s", msg.from_addr, msg.subject)
        result = classify_email(msg)
        stats.classified += 1

        if result.category == "action-required":
            stats.action_required += 1
            send_telegram_notification(msg, result)
        elif result.category == "foundation-business":
            send_telegram_notification(msg, result)
        elif result.category in ("FYI-only", "newsletter", "spam"):
            stats.archived += 1
            log.info("Auto-archived: [%s] %s", result.category, msg.subject)
        else:
            stats.errors += 1

        seen.add(msg.uid)

    save_seen_uids(seen)
    log_poll_cost(stats)
    log.info(
        "Poll complete: %d fetched, %d classified, %d action-required, %d archived",
        stats.fetched, stats.classified, stats.action_required, stats.archived,
    )
    return stats


def _is_command_email(msg: EmailMessage) -> bool:
    """Check if an email is a command sent to the bot."""
    # Commands come from Bob/Ken to the bot's address
    bot_addresses = ["aigovops@", "bot@aigovops", "bobrapp+bot@"]
    subject_prefixes = ["cmd:", "command:", "bot:", "/"]
    
    to_lower = msg.to_addr.lower()
    subject_lower = msg.subject.lower()
    
    for addr in bot_addresses:
        if addr in to_lower:
            return True
    for prefix in subject_prefixes:
        if subject_lower.startswith(prefix):
            return True
    return False


def _handle_email_command(msg: EmailMessage) -> None:
    """Parse and execute a command from an email."""
    # Extract command from subject or body
    command = ""
    subject_lower = msg.subject.lower()
    
    for prefix in ["cmd:", "command:", "bot:", "/"]:
        if subject_lower.startswith(prefix):
            command = msg.subject[len(prefix):].strip()
            break
    
    if not command:
        command = msg.body.strip().split("\n")[0]  # First line of body
    
    if not command:
        return
    
    log.info("Email command from %s: %s", msg.from_addr, command[:50])
    
    try:
        # Import router lazily to avoid circular imports
        from scripts.command_router import CommandRouter
        from src.personal_foundation.v2.state import StateStore
        from src.personal_foundation.v2.cost_tracker import CostTracker
        from src.personal_foundation.v2.policy import PolicyEngine
        
        s = StateStore()
        ct = CostTracker(s)
        pe = PolicyEngine()
        
        # We need the call_llm function
        import scripts.run_bot as bot
        r = CommandRouter(s, ct, pe, bot.call_llm)
        result = r.route(command, username="bob")
        
        # Send result back via Telegram (since we can't easily reply to email)
        send_telegram_notification(
            EmailMessage(uid="cmd", from_addr="email-command", subject=command, body=result.text),
            ClassificationResult(category="foundation-business", confidence=1.0, reasoning="Email command result"),
        )
        
        s.log_audit(agent="system/email_cmd", action="command",
                   result_summary=f"Email cmd: {command[:50]}")
    except Exception as e:
        log.error("Email command failed: %s", e)


async def poll_loop() -> None:
    """Async poll loop — runs forever, polling every POLL_INTERVAL seconds."""
    log.info("Email poller started (interval: %ds)", POLL_INTERVAL)
    while True:
        try:
            stats = poll_once()
            if stats.classified > 0:
                log.info("Cycle stats: %s", json.dumps({
                    "classified": stats.classified,
                    "action_required": stats.action_required,
                    "archived": stats.archived,
                }))
        except Exception as e:
            log.error("Poll cycle failed: %s", e)
        await asyncio.sleep(POLL_INTERVAL)


# ─── Standalone entry point ───────────────────────────────────────────────────

def main():
    """Run the email poller as a standalone process."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
    )
    log.info("Starting email poller (standalone mode)")
    log.info("  IMAP user: %s", IMAP_USER)
    log.info("  Poll interval: %ds", POLL_INTERVAL)
    log.info("  OpenAI configured: %s", bool(OPENAI_KEY))
    log.info("  Telegram configured: %s", bool(TELEGRAM_TOKEN))

    asyncio.run(poll_loop())


if __name__ == "__main__":
    main()
