"""Agent base class for the personal + foundation automation system.

INTERNAL USE ONLY — not part of the ai-bob-setup-agent customer product.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.personal_foundation.audit_shim import log_action
from src.audit_log import AuditEntry

if TYPE_CHECKING:
    from src.personal_foundation.config import FoundationConfig
    from src.personal_foundation.approval_queue import ApprovalItem


class BaseAgent:
    """Base class for all personal and foundation automation agents.

    Every agent:
    - Has a prefixed agent name (personal/<name> or foundation/<name>)
    - Logs every action via the audit shim (enforces prefix)
    - Can queue items in the Approval_Queue via the Orchestrator
    - Respects dry_run mode (no external API calls when True)
    """

    agent_prefix: str  # "personal/" or "foundation/"
    agent_name: str    # e.g. "email_agent"

    def __init__(self, config: "FoundationConfig", dry_run: bool = False) -> None:
        self.config = config
        self.dry_run = dry_run
        self._orchestrator = None  # injected by Orchestrator after construction

    @property
    def full_agent_name(self) -> str:
        """Returns the fully-prefixed agent name, e.g. 'personal/email_agent'."""
        return f"{self.agent_prefix}{self.agent_name}"

    def log(
        self,
        action: str,
        command: str,
        status: str = "success",
        result_summary: str = "",
        model: str = "",
        details: dict | None = None,
    ) -> AuditEntry:
        """Log an action to the audit log with the agent's prefix enforced.

        Args:
            action: Action verb, e.g. 'classify' or 'draft_reply'.
                    Will be prefixed as '<agent_prefix><agent_name>:<action>'.
            command: Verbatim command or prompt summary (max 200 chars).
            status: 'success', 'failure', or 'partial'.
            result_summary: Human-readable result summary (max 200 chars).
            model: AI model used (if any).
            details: Structured result data. Must NOT contain PII or credentials.

        Returns:
            The written AuditEntry.
        """
        full_action = f"{self.full_agent_name}:{action}"
        customer = "foundation" if self.agent_prefix == "foundation/" else "bob"
        return log_action(
            action=full_action,
            command=command,
            customer=customer,
            model=model,
            dry_run=self.dry_run,
            status=status,
            result_summary=result_summary,
            details=details or {},
        )

    def queue(self, item: "ApprovalItem") -> None:
        """Place an item in the Approval_Queue via the Orchestrator.

        Raises:
            RuntimeError: If the Orchestrator has not been injected.
        """
        if self._orchestrator is None:
            raise RuntimeError(
                f"Agent '{self.full_agent_name}' has no Orchestrator attached. "
                "Call orchestrator.register_agent(agent) before using queue()."
            )
        self._orchestrator.enqueue(item)
