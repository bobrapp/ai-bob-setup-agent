"""Natural language command parser — understands casual Telegram messages.

Instead of: /suspend personal/email_agent
Bob can type: "pause the email agent" or "stop moderator for now"

Uses simple keyword matching (no LLM needed — fast and free).
Falls back to LLM parsing for ambiguous commands.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Agent name aliases (what Bob might say → actual agent name)
AGENT_ALIASES = {
    "email": "personal/email_classifier",
    "email agent": "personal/email_classifier",
    "emails": "personal/email_classifier",
    "calendar": "personal/calendar_agent",
    "research": "personal/research_scanner",
    "researcher": "personal/research_scanner",
    "writer": "foundation/writing_agent",
    "writing": "foundation/writing_agent",
    "content": "foundation/writing_agent",
    "task": "personal/task_agent",
    "tasks": "personal/task_agent",
    "welcomer": "foundation/welcomer",
    "welcome": "foundation/welcomer",
    "curator": "foundation/curator",
    "digest": "foundation/curator",
    "moderator": "foundation/moderator",
    "moderation": "foundation/moderator",
    "mod": "foundation/moderator",
}

# Command patterns: (regex, command_type)
COMMAND_PATTERNS = [
    # Suspend/pause
    (r"(?:suspend|pause|stop|disable|turn off|shut down)\s+(?:the\s+)?(.+?)(?:\s+agent)?(?:\s+for now)?$", "suspend"),
    # Resume/start
    (r"(?:resume|start|enable|turn on|unpause|restart)\s+(?:the\s+)?(.+?)(?:\s+agent)?$", "resume"),
    # Status
    (r"(?:status|how are things|what.s happening|system status|health)", "status"),
    # Pending
    (r"(?:what.s pending|pending|queue|approvals|what.s waiting|show queue)", "pending"),
    # Approve all
    (r"(?:approve all|approve everything|clear the queue|approve low risk)", "approve_all_low_risk"),
    # Draft
    (r"(?:draft|write|create)\s+(?:a\s+)?(?:post\s+)?(?:about\s+)?(.+)", "draft"),
    # Summary
    (r"(?:summary|what did|today.s activity|daily report|what happened today)", "daily_summary"),
    # Help
    (r"(?:help|commands|what can you do|options)", "help"),
]


@dataclass
class ParsedCommand:
    """A parsed natural language command."""
    command: str        # suspend, resume, status, pending, draft, etc.
    params: dict        # {agent: "...", topic: "...", etc.}
    confidence: float   # How confident we are in the parse (0-1)
    original: str       # The original text


def parse_natural_language(text: str) -> ParsedCommand:
    """Parse a natural language message into a structured command.

    Examples:
        "pause the email agent" → ParsedCommand(command="suspend", params={"agent": "personal/email_classifier"})
        "what's in my queue" → ParsedCommand(command="pending", params={})
        "draft about AI trends" → ParsedCommand(command="draft", params={"topic": "AI trends"})
    """
    text_lower = text.lower().strip()

    # Try each pattern
    for pattern, command_type in COMMAND_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            params = _extract_params(command_type, match, text_lower)
            return ParsedCommand(
                command=command_type,
                params=params,
                confidence=0.9,
                original=text,
            )

    # No pattern matched — check if it's just an agent name (implies status)
    for alias, agent_name in AGENT_ALIASES.items():
        if alias in text_lower and len(text_lower) < 30:
            return ParsedCommand(
                command="agent_status",
                params={"agent": agent_name},
                confidence=0.6,
                original=text,
            )

    # Truly unrecognized
    return ParsedCommand(
        command="unknown",
        params={"raw": text},
        confidence=0.0,
        original=text,
    )


def _extract_params(command_type: str, match: re.Match, text: str) -> dict:
    """Extract parameters from a regex match."""
    if command_type in ("suspend", "resume"):
        agent_text = match.group(1).strip() if match.lastindex else ""
        agent_name = _resolve_agent_name(agent_text)
        return {"agent": agent_name}

    elif command_type == "draft":
        topic = match.group(1).strip() if match.lastindex else text
        return {"topic": topic}

    return {}


def _resolve_agent_name(text: str) -> str:
    """Resolve a casual agent reference to the full agent name."""
    text_clean = text.lower().strip().rstrip(".")

    # Direct alias match
    if text_clean in AGENT_ALIASES:
        return AGENT_ALIASES[text_clean]

    # Partial match
    for alias, name in AGENT_ALIASES.items():
        if alias in text_clean:
            return name

    # Return as-is (might be the full name already)
    if "/" in text_clean:
        return text_clean

    return f"unknown/{text_clean}"


def format_help() -> str:
    """Return a help message showing available natural language commands."""
    return """🤖 I understand natural language! Try:

**Control agents:**
• "pause the email agent"
• "resume moderator"
• "stop research for now"

**Check status:**
• "what's pending?"
• "status"
• "what did my agents do today?"

**Take action:**
• "approve all low risk"
• "draft about AI governance trends"

**Or use slash commands:**
/status /pending /suspend /resume /help"""
