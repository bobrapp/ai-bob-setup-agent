"""Telegram-controlled meta-agent.

Per the source episode, Nick runs a single Telegram channel through which a
meta-agent installs Hermes, manages 27 VMs, and patches problems on the fly.
This module is the operator-side controller for that channel.

It sends notifications and receives commands. Outbound is implemented; the
inbound command loop is a documented extension point that runs under
`make watchdog` in long-running deployments.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
import structlog

log = structlog.get_logger(__name__)


@dataclass
class TelegramConfig:
    bot_token: str
    control_chat_id: str

    @classmethod
    def from_env(cls) -> "TelegramConfig":
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat = os.getenv("TELEGRAM_CONTROL_CHAT_ID", "")
        return cls(bot_token=token, control_chat_id=chat)

    @property
    def configured(self) -> bool:
        return bool(self.bot_token and self.control_chat_id)


class TelegramMeta:
    """Outbound notifier + command-channel scaffold."""

    BASE = "https://api.telegram.org"

    def __init__(self, config: TelegramConfig | None = None, dry_run: bool = False) -> None:
        self.config = config or TelegramConfig.from_env()
        self.dry_run = dry_run

    def send(self, text: str, parse_mode: str = "Markdown") -> bool:
        if not self.config.configured:
            log.warning("telegram.unconfigured", text=text[:80])
            return False
        if self.dry_run:
            log.info("telegram.dry_run", text=text[:120])
            return True
        url = f"{self.BASE}/bot{self.config.bot_token}/sendMessage"
        try:
            with httpx.Client(timeout=10.0) as client:
                r = client.post(
                    url,
                    json={
                        "chat_id": self.config.control_chat_id,
                        "text": text,
                        "parse_mode": parse_mode,
                    },
                )
            ok = r.status_code == 200
            if not ok:
                log.warning("telegram.send_failed", status=r.status_code, body=r.text[:200])
            return ok
        except Exception as exc:  # noqa: BLE001 — outbound notifier must not crash callers
            log.error("telegram.send_error", error=str(exc))
            return False

    def notify_provisioned(self, customer_slug: str, agents: list[str]) -> None:
        self.send(
            f"*Provisioned* `{customer_slug}` with {len(agents)} agent(s):\n"
            + "\n".join(f"  • {a}" for a in agents)
        )

    def notify_watchdog_fired(self, customer_slug: str, agent_name: str, reason: str) -> None:
        self.send(
            f"⚠️ *Watchdog* `{customer_slug}` / `{agent_name}`\n"
            f"Reason: {reason}\n"
            f"Action: investigate via `make health`"
        )

    def notify_decommissioned(self, customer_slug: str) -> None:
        self.send(f"*Decommissioned* `{customer_slug}` — workspace torn down, logs archived.")

    # ---------------------------------------------------------------------
    # Inbound command loop (documented extension point)
    # ---------------------------------------------------------------------
    def listen(self) -> None:
        """Long-poll Telegram and dispatch commands to the meta-agent.

        Recommended commands (per the source episode):
          /status               — list customers and agent health
          /restart <cust> <a>   — restart a specific agent
          /install <cust> <a>   — provision a new agent for an existing customer
          /logs <cust> <a>      — tail the agent's recent operational logs
          /panic                — page Bob immediately, pause provisioning

        Implement via `python-telegram-bot` Application + CommandHandler.
        Run under `make watchdog` or as a systemd unit on the operator host.
        """
        log.warning("telegram.listen.unimplemented", note="run via python-telegram-bot Application")
