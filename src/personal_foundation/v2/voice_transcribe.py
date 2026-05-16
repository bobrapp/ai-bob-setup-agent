"""Voice transcription — converts Telegram voice messages to text commands.

When Bob sends a voice note to the Telegram bot, this module:
1. Downloads the audio file
2. Transcribes it using OpenAI Whisper API (or Groq whisper)
3. Parses the transcription into a command
4. Executes the command via the voice API

Supports natural language: "approve the first item", "what's in my queue",
"draft something about AI governance trends"
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

import httpx

from src.personal_foundation.v2.state import StateStore

log = logging.getLogger(__name__)

WHISPER_API_URL = "https://api.openai.com/v1/audio/transcriptions"
GROQ_WHISPER_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# Command patterns (simple keyword matching)
COMMAND_PATTERNS = {
    "whats_pending": ["what's pending", "whats pending", "what is pending", "check queue", "approval queue"],
    "approve_all_low_risk": ["approve low risk", "approve all", "batch approve", "approve safe"],
    "daily_summary": ["daily summary", "what did", "today's activity", "agent summary", "what happened"],
    "suspend": ["suspend", "pause", "stop agent"],
    "draft": ["draft", "write about", "create a post", "write something"],
}


class VoiceTranscriber:
    """Transcribes voice messages and maps to commands."""

    def __init__(self, store: StateStore, provider: str = "openai") -> None:
        self.store = store
        self.provider = provider  # "openai" or "groq"
        self._api_key = os.getenv("OPENAI_API_KEY", "") if provider == "openai" else os.getenv("GROQ_API_KEY", "")

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def transcribe_file(self, audio_path: str | Path) -> str:
        """Transcribe an audio file to text using Whisper."""
        if not self.is_configured:
            log.warning("VoiceTranscriber: API key not configured for %s", self.provider)
            return ""

        url = WHISPER_API_URL if self.provider == "openai" else GROQ_WHISPER_URL
        model = "whisper-1" if self.provider == "openai" else "whisper-large-v3"

        async with httpx.AsyncClient(timeout=30) as client:
            with open(audio_path, "rb") as f:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    files={"file": (Path(audio_path).name, f, "audio/ogg")},
                    data={"model": model, "language": "en"},
                )

            if resp.status_code == 200:
                text = resp.json().get("text", "")
                log.info("VoiceTranscriber: transcribed %d chars", len(text))
                self.store.log_audit(
                    agent="system/voice", action="transcribe",
                    status="success", model=model,
                    result_summary=f"Transcribed: {text[:100]}",
                )
                return text
            else:
                log.error("VoiceTranscriber: API error %d: %s", resp.status_code, resp.text[:200])
                return ""

    def parse_command(self, text: str) -> dict:
        """Parse transcribed text into a voice command.

        Returns: {"command": str, "params": dict}
        """
        text_lower = text.lower().strip()

        # Check each command pattern
        for command, patterns in COMMAND_PATTERNS.items():
            for pattern in patterns:
                if pattern in text_lower:
                    params = self._extract_params(command, text_lower)
                    return {"command": command, "params": params}

        # Default: treat as a draft request if it's long enough
        if len(text_lower) > 20:
            return {"command": "draft", "params": {"topic": text}}

        return {"command": "unknown", "params": {"raw_text": text}}

    def _extract_params(self, command: str, text: str) -> dict:
        """Extract parameters from the transcribed text."""
        if command == "suspend":
            # Try to find agent name after "suspend"
            parts = text.split("suspend", 1)
            if len(parts) > 1:
                agent = parts[1].strip().replace(" ", "_")
                # Map common names
                agent_map = {
                    "email": "personal/email_classifier",
                    "email_agent": "personal/email_classifier",
                    "moderator": "foundation/moderator",
                    "welcomer": "foundation/welcomer",
                    "research": "personal/research_scanner",
                    "writer": "foundation/writing_agent",
                    "writing": "foundation/writing_agent",
                }
                return {"agent": agent_map.get(agent, agent)}
            return {}

        elif command == "draft":
            # Extract topic after "draft about" or "write about"
            for prefix in ["draft about ", "write about ", "create a post about ", "draft "]:
                if prefix in text:
                    topic = text.split(prefix, 1)[1].strip()
                    return {"topic": topic}
            return {"topic": text}

        return {}

    async def process_voice_message(self, audio_path: str | Path) -> dict:
        """Full pipeline: transcribe → parse → return command.

        Returns: {"transcription": str, "command": str, "params": dict}
        """
        transcription = await self.transcribe_file(audio_path)
        if not transcription:
            return {"transcription": "", "command": "error", "params": {"error": "transcription_failed"}}

        parsed = self.parse_command(transcription)
        return {
            "transcription": transcription,
            "command": parsed["command"],
            "params": parsed["params"],
        }
