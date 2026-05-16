#!/usr/bin/env python3
"""Audit log viewer — read-only CLI for logs/audit.jsonl.

INTERNAL USE ONLY — not part of the ai-bob-setup-agent customer product.

Usage:
    python scripts/audit_viewer.py
    python scripts/audit_viewer.py --agent personal/email_agent
    python scripts/audit_viewer.py --status failure --date 2026-05-15
    python scripts/audit_viewer.py --limit 50

Displays the last 100 entries (default) with optional filtering by agent, date, and status.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDIT_LOG_FILE = REPO_ROOT / "logs" / "audit.jsonl"


def read_entries(limit: int = 100) -> list[dict]:
    """Read all entries from the audit log."""
    if not AUDIT_LOG_FILE.exists():
        return []
    entries = []
    with AUDIT_LOG_FILE.open("r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries[-limit:]


def filter_entries(
    entries: list[dict],
    agent: str | None = None,
    status: str | None = None,
    date: str | None = None,
) -> list[dict]:
    """Filter entries by agent, status, and/or date."""
    filtered = entries

    if agent:
        filtered = [e for e in filtered if agent in e.get("action", "")]

    if status:
        filtered = [e for e in filtered if e.get("status") == status]

    if date:
        filtered = [e for e in filtered if e.get("date") == date]

    return filtered


def format_table(entries: list[dict]) -> str:
    """Format entries as a readable table."""
    if not entries:
        return "No entries found."

    # Header
    header = f"{'#':>5} {'Timestamp':<20} {'Action':<40} {'Status':<10} {'Summary':<50}"
    separator = "-" * len(header)
    lines = [header, separator]

    for e in entries:
        seq = str(e.get("seq", ""))
        ts = (e.get("timestamp", "") or "")[:19]
        action = (e.get("action", "") or "")[:39]
        status = (e.get("status", "") or "")[:9]
        summary = (e.get("result_summary", "") or "")[:49]
        lines.append(f"{seq:>5} {ts:<20} {action:<40} {status:<10} {summary:<50}")

    lines.append(separator)
    lines.append(f"Total: {len(entries)} entries")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only audit log viewer for the personal + foundation automation system."
    )
    parser.add_argument(
        "--agent",
        type=str,
        default=None,
        help="Filter by agent name (e.g. 'personal/email_agent')",
    )
    parser.add_argument(
        "--status",
        type=str,
        default=None,
        choices=["success", "failure", "partial", "started", "aborted"],
        help="Filter by status",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Filter by date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of entries to display (default: 100)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of table",
    )

    args = parser.parse_args()

    if not AUDIT_LOG_FILE.exists():
        print(f"Audit log not found at {AUDIT_LOG_FILE}")
        print("No agent actions have been logged yet.")
        sys.exit(0)

    entries = read_entries(limit=args.limit)
    filtered = filter_entries(entries, agent=args.agent, status=args.status, date=args.date)

    if args.json:
        print(json.dumps(filtered, indent=2, default=str))
    else:
        print(format_table(filtered))


if __name__ == "__main__":
    main()
