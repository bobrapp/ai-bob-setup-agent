"""Audit shim for the personal + foundation automation system.

INTERNAL USE ONLY — not part of the ai-bob-setup-agent customer product.

Thin wrapper over src/audit_log.py that enforces the personal/ or foundation/
prefix on every action field. Raises ValueError if an unprefixed action is passed.

Usage:
    from src.personal_foundation.audit_shim import log_action

    log_action(
        action="personal/email_agent:classify",
        command="classify email id=abc123",
        customer="bob",
        ...
    )
"""

from __future__ import annotations

from src.audit_log import AuditEntry, log_action as _base_log_action

VALID_PREFIXES = ("personal/", "foundation/")


def log_action(
    action: str,
    command: str,
    customer: str = "bob",
    model: str = "",
    dry_run: bool = False,
    status: str = "success",
    result_summary: str = "",
    details: dict | None = None,
) -> AuditEntry:
    """Log an agent action with enforced personal/ or foundation/ prefix.

    Args:
        action: Action identifier. MUST start with 'personal/' or 'foundation/'.
                Example: 'personal/email_agent:classify'
        command: Verbatim command or prompt summary (max 200 chars).
        customer: 'bob' for personal actions, 'foundation' for foundation actions.
        model: AI model used (if any).
        dry_run: If True, records the intended action without executing it.
        status: 'success', 'failure', or 'partial'.
        result_summary: Human-readable result summary (max 200 chars).
        details: Structured result data. Must NOT contain PII, credentials, or tokens.

    Returns:
        The written AuditEntry.

    Raises:
        ValueError: If action does not start with 'personal/' or 'foundation/'.
    """
    if not any(action.startswith(prefix) for prefix in VALID_PREFIXES):
        raise ValueError(
            f"Audit action '{action}' must start with one of {VALID_PREFIXES}. "
            f"Personal agents use 'personal/<agent>:<verb>', "
            f"foundation agents use 'foundation/<agent>:<verb>'."
        )

    # Enforce summary length limits per Requirement 10.1
    if len(command) > 200:
        command = command[:197] + "..."
    if len(result_summary) > 200:
        result_summary = result_summary[:197] + "..."

    return _base_log_action(
        action=action,
        command=command,
        customer=customer,
        model=model,
        dry_run=dry_run,
        status=status,
        result_summary=result_summary,
        details=details or {},
    )
