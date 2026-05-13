"""Watchdog + email-based observability.

Per the source episode, the difference between a hobby setup and a $1M business
is catching agent failures before the customer notices. Every cloud computer
emits heartbeats; missing heartbeats trigger Telegram + email alerts.
"""

from __future__ import annotations

import asyncio
import os
import smtplib
from dataclasses import dataclass
from datetime import datetime, timezone
from email.mime.text import MIMEText

import structlog

from .config import CustomerConfig
from .orgo_client import CloudComputer, OrgoClient
from .telegram_meta import TelegramMeta

log = structlog.get_logger(__name__)


@dataclass
class HealthCheck:
    customer_slug: str
    agent_name: str
    cloud_computer_id: str
    status: str  # "healthy" | "degraded" | "down" | "unknown"
    last_heartbeat: datetime | None
    reason: str = ""


class Watchdog:
    """Polls customer agents and fires alerts on failure."""

    def __init__(
        self,
        orgo: OrgoClient,
        telegram: TelegramMeta | None = None,
        interval_seconds: int | None = None,
    ) -> None:
        self.orgo = orgo
        self.telegram = telegram or TelegramMeta()
        self.interval_seconds = interval_seconds or int(
            os.getenv("WATCHDOG_INTERVAL_SECONDS", "300")
        )

    # ---------------------------------------------------------------------
    # Single-pass check
    # ---------------------------------------------------------------------
    def check(self, customer: CustomerConfig) -> list[HealthCheck]:
        ws = self.orgo.get_workspace_by_slug(customer.customer.slug)
        results: list[HealthCheck] = []
        if not ws:
            for agent in customer.agents:
                results.append(
                    HealthCheck(
                        customer_slug=customer.customer.slug,
                        agent_name=agent.name,
                        cloud_computer_id="",
                        status="down",
                        last_heartbeat=None,
                        reason="workspace not found",
                    )
                )
            return results

        computers_by_name = {
            cc.agent_name: cc for cc in self.orgo.list_cloud_computers(ws.id)
        }
        for agent in customer.agents:
            cc = computers_by_name.get(agent.name)
            if not cc:
                results.append(
                    HealthCheck(
                        customer_slug=customer.customer.slug,
                        agent_name=agent.name,
                        cloud_computer_id="",
                        status="down",
                        last_heartbeat=None,
                        reason="cloud computer not found",
                    )
                )
                continue
            results.append(self._evaluate(customer.customer.slug, agent.name, cc))
        return results

    def _evaluate(
        self, customer_slug: str, agent_name: str, cc: CloudComputer
    ) -> HealthCheck:
        now = datetime.now(timezone.utc)
        status_map = {
            "running": "healthy",
            "provisioning": "degraded",
            "stopped": "down",
            "error": "down",
        }
        status = status_map.get(cc.status, "unknown")
        return HealthCheck(
            customer_slug=customer_slug,
            agent_name=agent_name,
            cloud_computer_id=cc.id,
            status=status,
            last_heartbeat=now if status == "healthy" else None,
            reason="" if status == "healthy" else f"status={cc.status}",
        )

    # ---------------------------------------------------------------------
    # Alerting
    # ---------------------------------------------------------------------
    def alert(self, hc: HealthCheck) -> None:
        if hc.status == "healthy":
            return
        log.warning(
            "watchdog.fire",
            customer=hc.customer_slug,
            agent=hc.agent_name,
            status=hc.status,
            reason=hc.reason,
        )
        self.telegram.notify_watchdog_fired(hc.customer_slug, hc.agent_name, hc.reason)
        send_email_alert(hc)

    # ---------------------------------------------------------------------
    # Long-running loop
    # ---------------------------------------------------------------------
    async def run_forever(self, customers: list[CustomerConfig]) -> None:
        log.info(
            "watchdog.loop.start",
            customer_count=len(customers),
            interval=self.interval_seconds,
        )
        while True:
            for customer in customers:
                try:
                    for hc in self.check(customer):
                        self.alert(hc)
                except Exception as exc:  # noqa: BLE001
                    log.error(
                        "watchdog.check.error",
                        customer=customer.customer.slug,
                        error=str(exc),
                    )
            await asyncio.sleep(self.interval_seconds)


# ---------------------------------------------------------------------------
# Email alerting
# ---------------------------------------------------------------------------
def send_email_alert(hc: HealthCheck) -> bool:
    host = os.getenv("SMTP_HOST", "")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("ALERT_EMAIL_FROM", "")
    recipient = os.getenv("ALERT_EMAIL_TO", "")
    if not all([host, sender, recipient]):
        log.warning(
            "email.unconfigured",
            host=bool(host),
            sender=bool(sender),
            recipient=bool(recipient),
        )
        return False

    body = (
        f"Watchdog fired.\n\n"
        f"Customer: {hc.customer_slug}\n"
        f"Agent:    {hc.agent_name}\n"
        f"Status:   {hc.status}\n"
        f"Reason:   {hc.reason}\n"
        f"Computer: {hc.cloud_computer_id}\n"
    )
    msg = MIMEText(body)
    msg["Subject"] = (
        f"[ai-bob-setup-agent] {hc.status.upper()} — {hc.customer_slug}/{hc.agent_name}"
    )
    msg["From"] = sender
    msg["To"] = recipient

    try:
        with smtplib.SMTP(host, port) as server:
            server.starttls()
            if user and password:
                server.login(user, password)
            server.send_message(msg)
        log.info("email.alert.sent", to=recipient)
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("email.alert.failed", error=str(exc))
        return False
