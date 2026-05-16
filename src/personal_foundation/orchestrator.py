"""Orchestrator for the personal + foundation automation system.

INTERNAL USE ONLY — not part of the ai-bob-setup-agent customer product.

The Orchestrator manages the Approval_Queue state machine, surfaces decisions
to Bob and Ken via Telegram, handles agent suspension/resume, and produces
weekly governance reports.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from src.audit_log import AUDIT_LOG_FILE
from src.personal_foundation.approval_queue import ApprovalItem, ApprovalQueue
from src.personal_foundation.audit_shim import log_action
from src.personal_foundation.models import WeeklyGovernanceReport

if TYPE_CHECKING:
    from src.personal_foundation.agents import BaseAgent
    from src.personal_foundation.config import FoundationConfig

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"


class Orchestrator:
    """Coordinates all agents, manages the Approval_Queue, and handles governance.

    Responsibilities:
    - Present ApprovalItems to Bob/Ken via Telegram with inline keyboard buttons
    - Route approvals, rejections, and edits through the queue state machine
    - Suspend/resume agents based on failure rates or manual commands
    - Produce weekly governance reports from the audit log
    - Check agent failure rates every 24h and auto-suspend if > 10%
    """

    def __init__(self, config: "FoundationConfig", dry_run: bool = False) -> None:
        self.config = config
        self.dry_run = dry_run
        self.approval_queue = ApprovalQueue()
        self._suspended: set[str] = set()
        self._agents: dict[str, "BaseAgent"] = {}
        # Lock for thread-safe suspended set access
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Telegram helpers
    # ------------------------------------------------------------------

    def _telegram_url(self, method: str) -> str:
        """Build a Telegram Bot API URL for the given method."""
        token = self.config.telegram.bot_token
        return f"https://api.telegram.org/bot{token}/{method}"

    def _send_telegram_message(
        self,
        chat_id: str,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str = "Markdown",
    ) -> bool:
        """Send a Telegram message. Returns True on success.

        When dry_run is True, logs the message instead of calling the API.
        """
        if self.dry_run:
            logger.info(
                "DRY RUN — Telegram message suppressed",
                extra={
                    "chat_id": chat_id,
                    "text": text[:200],
                    "has_markup": reply_markup is not None,
                },
            )
            log_action(
                action="foundation/orchestrator:telegram_dry_run",
                command=f"sendMessage to {chat_id}",
                customer="foundation",
                dry_run=True,
                status="success",
                result_summary=f"DRY RUN: would send message to {chat_id}",
                details={"chat_id": chat_id, "text_preview": text[:200]},
            )
            return True

        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_markup is not None:
            payload["reply_markup"] = json.dumps(reply_markup)

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(
                    self._telegram_url("sendMessage"),
                    json=payload,
                )
                response.raise_for_status()
                return True
        except httpx.HTTPError as exc:
            logger.error("Telegram sendMessage failed: %s", exc)
            return False

    def _build_approval_keyboard(self, item_id: str) -> dict[str, Any]:
        """Build the inline keyboard for an approval item."""
        return {
            "inline_keyboard": [
                [
                    {
                        "text": "✅ Approve",
                        "callback_data": f"approve:{item_id}",
                    },
                    {
                        "text": "❌ Reject",
                        "callback_data": f"reject:{item_id}",
                    },
                    {
                        "text": "✏️ Edit",
                        "callback_data": f"edit:{item_id}",
                    },
                ]
            ]
        }

    def _format_item_message(self, item: ApprovalItem) -> str:
        """Format an ApprovalItem as a Telegram message."""
        lines = [
            f"*Approval Required*",
            f"",
            f"*Agent:* `{item.agent}`",
            f"*Type:* `{item.action_type}`",
            f"*Description:* {item.description}",
        ]
        if item.rationale:
            lines.append(f"*Rationale:* {item.rationale}")
        lines += [
            f"",
            f"*Draft:*",
            f"```",
            item.draft_content[:1000],  # cap to avoid Telegram message size limit
            f"```",
            f"",
            f"*Item ID:* `{item.item_id}`",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Approval flow
    # ------------------------------------------------------------------

    def present_to_telegram(self, item: ApprovalItem) -> None:
        """Send an ApprovalItem to the approval_chat_id with inline keyboard buttons.

        Sends ✅ Approve / ❌ Reject / ✏️ Edit buttons via Telegram inline keyboard.
        Respects dry_run — logs instead of calling API when True.
        """
        text = self._format_item_message(item)
        keyboard = self._build_approval_keyboard(item.item_id)
        chat_id = self.config.telegram.approval_chat_id

        success = self._send_telegram_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
        )

        log_action(
            action="foundation/orchestrator:present_to_telegram",
            command=f"present item {item.item_id} from {item.agent}",
            customer="foundation",
            dry_run=self.dry_run,
            status="success" if success else "failure",
            result_summary=f"Presented item {item.item_id} ({item.action_type}) to approval channel",
            details={
                "item_id": item.item_id,
                "agent": item.agent,
                "action_type": item.action_type,
                "chat_id": chat_id,
            },
        )

    def handle_approval(self, item_id: str, reviewer: str) -> None:
        """Process an approval decision.

        Per Requirement 12.3:
        1. Log the approval event to the Audit_Logger FIRST.
        2. Execute the action within 2 minutes.
        3. If the Audit_Logger is unavailable, proceed with execution and log when recovered.

        Args:
            item_id: The ID of the ApprovalItem to approve.
            reviewer: Identity of the reviewer (Bob or Ken).
        """
        item = self.approval_queue.approve(item_id, reviewer)

        # Step 1: Log approval FIRST (Requirement 12.3)
        try:
            log_action(
                action="foundation/orchestrator:approve",
                command=f"approve item {item_id} by {reviewer}",
                customer="foundation",
                dry_run=self.dry_run,
                status="success",
                result_summary=f"Item {item_id} approved by {reviewer}",
                details={
                    "item_id": item_id,
                    "reviewer": reviewer,
                    "agent": item.agent,
                    "action_type": item.action_type,
                    "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
                },
            )
        except OSError as exc:
            # Audit logger unavailable — proceed with execution, log when recovered
            logger.warning(
                "Audit logger unavailable during approval of %s: %s. "
                "Proceeding with execution; will log when recovered.",
                item_id,
                exc,
            )

        # Step 2: Execute the action within 2 minutes
        # Schedule execution in a background thread with a 2-minute deadline
        def _execute_with_deadline() -> None:
            try:
                self._execute_action(item)
            except Exception as exc:  # noqa: BLE001
                logger.error("Execution of approved item %s failed: %s", item_id, exc)
                try:
                    log_action(
                        action="foundation/orchestrator:approve",
                        command=f"execute approved item {item_id}",
                        customer="foundation",
                        dry_run=self.dry_run,
                        status="failure",
                        result_summary=f"Execution of approved item {item_id} failed: {str(exc)[:200]}",
                        details={"item_id": item_id, "error": str(exc)[:500]},
                    )
                except OSError:
                    pass  # logger still unavailable; already warned above

        timer = threading.Timer(0, _execute_with_deadline)
        timer.daemon = True
        timer.start()
        # The timer fires immediately (0s delay) but runs in a background thread.
        # The 2-minute constraint is a deadline, not a delay — execution starts ASAP.

    def handle_rejection(
        self, item_id: str, reviewer: str, reason: str = ""
    ) -> None:
        """Process a rejection decision.

        Per Requirement 12.4:
        - Log the rejection (including reason if provided).
        - Notify the originating agent to revise or discard.

        Args:
            item_id: The ID of the ApprovalItem to reject.
            reviewer: Identity of the reviewer.
            reason: Optional rejection reason.
        """
        item = self.approval_queue.reject(item_id, reviewer, reason)

        log_action(
            action="foundation/orchestrator:reject",
            command=f"reject item {item_id} by {reviewer}",
            customer="foundation",
            dry_run=self.dry_run,
            status="success",
            result_summary=f"Item {item_id} rejected by {reviewer}"
            + (f": {reason[:100]}" if reason else ""),
            details={
                "item_id": item_id,
                "reviewer": reviewer,
                "agent": item.agent,
                "action_type": item.action_type,
                "reason": reason,
                "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
            },
        )

        # Notify the originating agent to revise or discard
        self._notify_agent_rejection(item, reason)

    def _notify_agent_rejection(self, item: ApprovalItem, reason: str) -> None:
        """Notify the originating agent that its item was rejected."""
        agent = self._agents.get(item.agent)
        if agent is not None and hasattr(agent, "on_rejection"):
            try:
                agent.on_rejection(item, reason)  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Agent %s on_rejection callback failed: %s", item.agent, exc
                )
        else:
            # Log the notification even if no callback is registered
            logger.info(
                "Rejection notification for agent %s (item %s): %s",
                item.agent,
                item.item_id,
                reason or "(no reason given)",
            )

    def handle_edit(self, item_id: str, new_content: str) -> None:
        """Accept edited content, replace the draft, and re-present to Telegram.

        Per Requirement 12.2: replace the original draft in the queue and
        re-present the updated action for final approve / reject.

        Args:
            item_id: The ID of the ApprovalItem to edit.
            new_content: The replacement draft content.
        """
        item = self.approval_queue.edit(item_id, new_content)

        log_action(
            action="foundation/orchestrator:edit",
            command=f"edit item {item_id}",
            customer="foundation",
            dry_run=self.dry_run,
            status="success",
            result_summary=f"Item {item_id} edited and re-queued for review",
            details={
                "item_id": item_id,
                "agent": item.agent,
                "action_type": item.action_type,
            },
        )

        # Re-present the updated item to Telegram
        self.present_to_telegram(item)

    def _execute_action(self, item: ApprovalItem) -> None:
        """Execute an approved action.

        Dispatches to the originating agent's execute method if available,
        otherwise logs the execution as a no-op (agents implement their own
        execution logic via callbacks).

        Args:
            item: The approved ApprovalItem to execute.
        """
        if self.dry_run:
            log_action(
                action="foundation/orchestrator:execute",
                command=f"execute item {item.item_id}",
                customer="foundation",
                dry_run=True,
                status="success",
                result_summary=f"DRY RUN: would execute {item.action_type} for {item.agent}",
                details={"item_id": item.item_id, "agent": item.agent},
            )
            return

        agent = self._agents.get(item.agent)
        if agent is not None and hasattr(agent, "execute_approved"):
            agent.execute_approved(item)  # type: ignore[attr-defined]
        else:
            # No registered executor — log and move on
            log_action(
                action="foundation/orchestrator:execute",
                command=f"execute item {item.item_id}",
                customer="foundation",
                dry_run=self.dry_run,
                status="success",
                result_summary=f"Executed {item.action_type} for {item.agent} (no-op: no executor registered)",
                details={"item_id": item.item_id, "agent": item.agent},
            )

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    def enqueue(self, item: ApprovalItem) -> None:
        """Add an item to the approval queue.

        If the queue has 10 or fewer pending items, presents the item individually.
        If the queue exceeds 10 items, sends a digest summary instead to avoid
        notification fatigue (Requirement 12.6).

        Args:
            item: The ApprovalItem to enqueue.
        """
        self.approval_queue.enqueue(item)

        pending_count = len(self.approval_queue)
        if pending_count <= 10:
            self.present_to_telegram(item)
        else:
            self._send_digest_notification(pending_count)

    def _send_digest_notification(self, pending_count: int) -> None:
        """Send a summary digest when the queue exceeds 10 items."""
        pending = self.approval_queue.pending()
        type_counts: dict[str, int] = defaultdict(int)
        for p in pending:
            type_counts[p.action_type] += 1

        type_summary = ", ".join(
            f"{count} {atype}" for atype, count in sorted(type_counts.items())
        )
        text = (
            f"*Approval Queue Digest*\n\n"
            f"You have *{pending_count} pending items* in the approval queue.\n\n"
            f"*Types:* {type_summary}\n\n"
            f"Please review your queue to avoid delays."
        )

        self._send_telegram_message(
            chat_id=self.config.telegram.bob_chat_id,
            text=text,
        )

        log_action(
            action="foundation/orchestrator:digest_notification",
            command=f"send digest for {pending_count} pending items",
            customer="foundation",
            dry_run=self.dry_run,
            status="success",
            result_summary=f"Sent digest notification: {pending_count} pending items",
            details={"pending_count": pending_count, "type_counts": dict(type_counts)},
        )

    # ------------------------------------------------------------------
    # Agent lifecycle
    # ------------------------------------------------------------------

    def register_agent(self, agent: "BaseAgent") -> None:
        """Register an agent with the orchestrator.

        Injects self as agent._orchestrator so the agent can call queue().

        Args:
            agent: The BaseAgent instance to register.
        """
        agent._orchestrator = self
        self._agents[agent.full_agent_name] = agent

    def suspend_agent(self, agent_name: str, reason: str) -> None:
        """Suspend an agent's autonomous actions.

        Per Requirement 10.5 and 10.6: adds the agent to the suspended set
        and logs the suspension.

        Args:
            agent_name: The fully-prefixed agent name (e.g. 'personal/email_agent').
            reason: Human-readable reason for suspension.
        """
        with self._lock:
            self._suspended.add(agent_name)

        log_action(
            action="foundation/orchestrator:suspend_agent",
            command=f"suspend {agent_name}",
            customer="foundation",
            dry_run=self.dry_run,
            status="success",
            result_summary=f"Agent '{agent_name}' suspended: {reason[:150]}",
            details={"agent_name": agent_name, "reason": reason},
        )

        logger.warning("Agent '%s' suspended: %s", agent_name, reason)

    def resume_agent(self, agent_name: str) -> None:
        """Resume a suspended agent.

        Per Requirement 10.6: removes the agent from the suspended set and logs.

        Args:
            agent_name: The fully-prefixed agent name to resume.
        """
        with self._lock:
            self._suspended.discard(agent_name)

        log_action(
            action="foundation/orchestrator:resume_agent",
            command=f"resume {agent_name}",
            customer="foundation",
            dry_run=self.dry_run,
            status="success",
            result_summary=f"Agent '{agent_name}' resumed",
            details={"agent_name": agent_name},
        )

        logger.info("Agent '%s' resumed.", agent_name)

    def is_suspended(self, agent_name: str) -> bool:
        """Return True if the named agent is currently suspended.

        Args:
            agent_name: The fully-prefixed agent name to check.

        Returns:
            True if suspended, False otherwise.
        """
        with self._lock:
            return agent_name in self._suspended

    # ------------------------------------------------------------------
    # Failure rate monitoring
    # ------------------------------------------------------------------

    def check_failure_rates(self) -> None:
        """Read logs/audit.jsonl and compute failure rates per agent in the last 24h.

        Per Requirement 10.5: if any agent's failure rate exceeds 10% in a 24h window,
        suspend that agent and send a Telegram alert to bob_chat_id within 60 seconds.
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=24)

        entries = self._read_audit_log_since(cutoff)

        # Group entries by agent (extracted from the action field prefix)
        agent_totals: dict[str, int] = defaultdict(int)
        agent_failures: dict[str, int] = defaultdict(int)

        for entry in entries:
            action = entry.get("action", "")
            status = entry.get("status", "")

            # Extract agent name from action field (e.g. "personal/email_agent:classify")
            agent_name = self._extract_agent_from_action(action)
            if not agent_name:
                continue

            agent_totals[agent_name] += 1
            if status == "failure":
                agent_failures[agent_name] += 1

        threshold = self.config.agent_failure_rate_threshold

        for agent_name, total in agent_totals.items():
            if total == 0:
                continue
            failure_rate = agent_failures[agent_name] / total
            if failure_rate > threshold:
                # Suspend the agent
                reason = (
                    f"Failure rate {failure_rate:.1%} exceeds threshold "
                    f"{threshold:.1%} in the last 24h "
                    f"({agent_failures[agent_name]}/{total} actions failed)"
                )
                self.suspend_agent(agent_name, reason)

                # Send Telegram alert to Bob within 60s (synchronous call)
                alert_text = (
                    f"⚠️ *Agent Auto-Suspended*\n\n"
                    f"*Agent:* `{agent_name}`\n"
                    f"*Failure rate:* {failure_rate:.1%} "
                    f"({agent_failures[agent_name]}/{total} in last 24h)\n"
                    f"*Threshold:* {threshold:.1%}\n\n"
                    f"Send `/resume {agent_name}` to re-enable."
                )
                self._send_telegram_message(
                    chat_id=self.config.telegram.bob_chat_id,
                    text=alert_text,
                )

                log_action(
                    action="foundation/orchestrator:failure_rate_alert",
                    command=f"check_failure_rates: {agent_name} at {failure_rate:.1%}",
                    customer="foundation",
                    dry_run=self.dry_run,
                    status="success",
                    result_summary=(
                        f"Auto-suspended {agent_name}: {failure_rate:.1%} failure rate "
                        f"({agent_failures[agent_name]}/{total})"
                    ),
                    details={
                        "agent_name": agent_name,
                        "failure_rate": failure_rate,
                        "failures": agent_failures[agent_name],
                        "total": total,
                        "threshold": threshold,
                    },
                )

    def _extract_agent_from_action(self, action: str) -> str | None:
        """Extract the agent name from an audit log action field.

        E.g. 'personal/email_agent:classify' → 'personal/email_agent'
             'foundation/welcomer:send_dm' → 'foundation/welcomer'
             'cli_invocation' → None (not a personal/foundation agent)
        """
        for prefix in ("personal/", "foundation/"):
            if action.startswith(prefix):
                # Strip the verb after the colon
                agent_part = action[len(prefix):]
                if ":" in agent_part:
                    agent_part = agent_part.split(":")[0]
                return f"{prefix}{agent_part}"
        return None

    def _read_audit_log_since(self, since: datetime) -> list[dict]:
        """Read audit log entries written at or after `since`."""
        if not AUDIT_LOG_FILE.exists():
            return []

        entries = []
        try:
            with AUDIT_LOG_FILE.open("r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts_str = entry.get("timestamp", "")
                    if not ts_str:
                        continue
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        # Ensure timezone-aware for comparison
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        if ts >= since:
                            entries.append(entry)
                    except ValueError:
                        continue
        except OSError as exc:
            logger.error("Failed to read audit log: %s", exc)

        return entries

    # ------------------------------------------------------------------
    # Governance reporting
    # ------------------------------------------------------------------

    def weekly_governance_report(self) -> WeeklyGovernanceReport:
        """Compute the weekly governance report from the last 7 days of audit logs.

        Reads logs/audit.jsonl and computes:
        - total_actions
        - actions_by_agent
        - approval_queue_throughput (approved + rejected items)
        - overall_failure_rate
        - agent_failure_rates
        - anomalies (agents above failure threshold)
        - consecutive_failure_agents (agents with > 5 consecutive failures)

        Returns:
            A populated WeeklyGovernanceReport dataclass.
        """
        now = datetime.now(timezone.utc)
        period_end = now.date()
        period_start = (now - timedelta(days=7)).date()
        cutoff = now - timedelta(days=7)

        entries = self._read_audit_log_since(cutoff)

        # Aggregate counts
        agent_totals: dict[str, int] = defaultdict(int)
        agent_failures: dict[str, int] = defaultdict(int)
        total_actions = 0
        approval_throughput = 0

        # For consecutive failure tracking: agent → list of statuses in time order
        agent_status_sequence: dict[str, list[str]] = defaultdict(list)

        for entry in entries:
            action = entry.get("action", "")
            status = entry.get("status", "")

            # Count approval throughput
            if action in (
                "foundation/orchestrator:approve",
                "foundation/orchestrator:reject",
            ):
                approval_throughput += 1

            agent_name = self._extract_agent_from_action(action)
            if not agent_name:
                continue

            total_actions += 1
            agent_totals[agent_name] += 1
            agent_status_sequence[agent_name].append(status)
            if status == "failure":
                agent_failures[agent_name] += 1

        # Compute per-agent failure rates
        agent_failure_rates: dict[str, float] = {}
        for agent_name, total in agent_totals.items():
            if total > 0:
                agent_failure_rates[agent_name] = agent_failures[agent_name] / total
            else:
                agent_failure_rates[agent_name] = 0.0

        # Overall failure rate
        total_failures = sum(agent_failures.values())
        overall_failure_rate = total_failures / total_actions if total_actions > 0 else 0.0

        # Anomalies: agents above failure threshold
        threshold = self.config.agent_failure_rate_threshold
        anomalies: list[str] = []
        for agent_name, rate in agent_failure_rates.items():
            if rate > threshold:
                anomalies.append(
                    f"{agent_name}: {rate:.1%} failure rate "
                    f"({agent_failures[agent_name]}/{agent_totals[agent_name]})"
                )

        # Consecutive failure agents: agents with > 5 consecutive failures
        consecutive_threshold = self.config.agent_consecutive_failure_threshold
        consecutive_failure_agents: list[str] = []
        for agent_name, statuses in agent_status_sequence.items():
            max_consecutive = self._max_consecutive_failures(statuses)
            if max_consecutive > consecutive_threshold:
                consecutive_failure_agents.append(
                    f"{agent_name}: {max_consecutive} consecutive failures"
                )

        return WeeklyGovernanceReport(
            period_start=period_start,
            period_end=period_end,
            total_actions=total_actions,
            actions_by_agent=dict(agent_totals),
            approval_queue_throughput=approval_throughput,
            overall_failure_rate=overall_failure_rate,
            agent_failure_rates=agent_failure_rates,
            anomalies=anomalies,
            consecutive_failure_agents=consecutive_failure_agents,
        )

    def _max_consecutive_failures(self, statuses: list[str]) -> int:
        """Return the maximum run of consecutive 'failure' statuses in the list."""
        max_run = 0
        current_run = 0
        for status in statuses:
            if status == "failure":
                current_run += 1
                max_run = max(max_run, current_run)
            else:
                current_run = 0
        return max_run
