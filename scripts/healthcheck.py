#!/usr/bin/env python3
"""One-pass health check across every configured customer.

Prints a table of agent statuses and exits non-zero if any are unhealthy.
Designed to be cron-able and CI-friendly.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

from src.config import list_customers, load_customer, load_env  # noqa: E402
from src.observability import Watchdog  # noqa: E402
from src.orgo_client import OrgoClient  # noqa: E402

console = Console()


def main() -> int:
    load_env()
    slugs = list_customers()
    if not slugs:
        console.print("[yellow]No customers configured.[/yellow]")
        return 0

    orgo = OrgoClient(dry_run=False)
    wd = Watchdog(orgo)

    table = Table(title="Agent health")
    table.add_column("Customer")
    table.add_column("Agent")
    table.add_column("Status")
    table.add_column("Reason")

    any_bad = False
    for slug in slugs:
        c = load_customer(slug)
        for hc in wd.check(c):
            colour = {
                "healthy": "green",
                "degraded": "yellow",
                "down": "red",
                "unknown": "magenta",
            }.get(hc.status, "white")
            table.add_row(
                hc.customer_slug,
                hc.agent_name,
                f"[{colour}]{hc.status}[/{colour}]",
                hc.reason,
            )
            if hc.status not in {"healthy"}:
                any_bad = True

    console.print(table)
    return 1 if any_bad else 0


if __name__ == "__main__":
    sys.exit(main())
