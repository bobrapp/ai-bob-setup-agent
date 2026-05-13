"""AIGovOps sequential audit logger.

Per the AIGovOps Foundation "how I built this" provenance rule, every
operational action must be logged with: operator, timestamp, model used,
prompt/command verbatim, result summary, and version (git SHA).

Logs are append-only JSONL files stored in logs/audit.jsonl. Each line is
a self-contained JSON record — easy to grep, ingest into observability
tools, or replay for compliance audits.
"""

from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDIT_LOG_DIR = REPO_ROOT / "logs"
AUDIT_LOG_FILE = AUDIT_LOG_DIR / "audit.jsonl"


@dataclass
class AuditEntry:
    """A single audit log record per the AIGovOps provenance standard."""

    # Who
    operator: str
    operator_email: str

    # When
    timestamp: str  # ISO 8601 UTC
    date: str  # YYYY-MM-DD for quick filtering
    time: str  # HH:MM:SS UTC

    # What
    action: str  # e.g. "onboard", "add-agent", "decommission", "healthcheck"
    command: str  # verbatim CLI command or prompt
    customer: str  # customer slug (if applicable)

    # How
    model: str  # AI model used (if any)
    dry_run: bool

    # Result
    status: str  # "success", "failure", "partial", "aborted"
    result_summary: str  # human-readable summary
    details: dict = field(default_factory=dict)  # structured result data

    # Version
    git_sha: str = ""  # short SHA of current HEAD
    git_branch: str = ""
    version: str = "0.1.0"

    # Sequence
    seq: int = 0  # auto-incremented sequence number


def _get_git_info() -> tuple[str, str]:
    """Return (short_sha, branch) from git. Gracefully handles missing git."""
    try:
        sha = (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(REPO_ROOT),
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
        branch = (
            subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(REPO_ROOT),
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
        return sha, branch
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "", ""


def _get_operator() -> tuple[str, str]:
    """Return (name, email) from env or system."""
    name = os.getenv("BOB_OPERATOR_NAME", getpass.getuser())
    email = os.getenv("BOB_OPERATOR_EMAIL", "")
    return name, email


def _next_seq() -> int:
    """Read the last sequence number from the audit log and return next."""
    if not AUDIT_LOG_FILE.exists():
        return 1
    try:
        # Read the last line
        with AUDIT_LOG_FILE.open("r") as f:
            last_line = ""
            for line in f:
                line = line.strip()
                if line:
                    last_line = line
            if not last_line:
                return 1
            data = json.loads(last_line)
            return data.get("seq", 0) + 1
    except (json.JSONDecodeError, OSError):
        return 1


def log_action(
    action: str,
    command: str,
    customer: str = "",
    model: str = "",
    dry_run: bool = False,
    status: str = "success",
    result_summary: str = "",
    details: dict | None = None,
) -> AuditEntry:
    """Append an audit entry to the log file. Returns the entry."""
    now = datetime.now(timezone.utc)
    operator_name, operator_email = _get_operator()
    git_sha, git_branch = _get_git_info()
    seq = _next_seq()

    entry = AuditEntry(
        operator=operator_name,
        operator_email=operator_email,
        timestamp=now.isoformat(),
        date=now.strftime("%Y-%m-%d"),
        time=now.strftime("%H:%M:%S"),
        action=action,
        command=command,
        customer=customer,
        model=model or os.getenv("DEFAULT_MODEL", ""),
        dry_run=dry_run,
        status=status,
        result_summary=result_summary,
        details=details or {},
        git_sha=git_sha,
        git_branch=git_branch,
        seq=seq,
    )

    # Ensure log directory exists
    AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Append as JSONL
    try:
        with AUDIT_LOG_FILE.open("a") as f:
            f.write(json.dumps(asdict(entry), default=str) + "\n")
        log.info(
            "audit.logged",
            seq=seq,
            action=action,
            customer=customer,
            status=status,
        )
    except OSError as exc:
        log.error("audit.write_failed", error=str(exc))

    return entry


def log_cli_invocation(dry_run: bool = False) -> AuditEntry:
    """Log the raw CLI invocation. Call at the start of every command."""
    command = " ".join(sys.argv)
    return log_action(
        action="cli_invocation",
        command=command,
        dry_run=dry_run,
        status="started",
        result_summary=f"CLI invoked: {command}",
    )


def read_log(limit: int = 50) -> list[dict]:
    """Read the last N entries from the audit log."""
    if not AUDIT_LOG_FILE.exists():
        return []
    entries = []
    try:
        with AUDIT_LOG_FILE.open("r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        return []
    return entries[-limit:]


def print_log(limit: int = 20) -> None:
    """Pretty-print recent audit log entries."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    entries = read_log(limit)

    if not entries:
        console.print("[yellow]No audit log entries found.[/yellow]")
        return

    table = Table(title="AIGovOps Audit Log", show_lines=False, padding=(0, 1))
    table.add_column("#", style="dim", justify="right")
    table.add_column("Timestamp", style="dim")
    table.add_column("Operator")
    table.add_column("Action", style="cyan")
    table.add_column("Customer")
    table.add_column("Status")
    table.add_column("Summary")

    for e in entries:
        status = e.get("status", "")
        colour = {
            "success": "green",
            "failure": "red",
            "partial": "yellow",
            "started": "blue",
            "aborted": "dim",
        }.get(status, "white")
        table.add_row(
            str(e.get("seq", "")),
            e.get("timestamp", "")[:19],
            e.get("operator", ""),
            e.get("action", ""),
            e.get("customer", "") or "—",
            f"[{colour}]{status}[/{colour}]",
            (e.get("result_summary", "") or "")[:60],
        )

    console.print(table)
