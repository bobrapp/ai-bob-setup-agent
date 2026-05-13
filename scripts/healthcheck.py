#!/usr/bin/env python3
"""One-shot health check across all configured customers.

Run via `make health` or directly:
    python scripts/healthcheck.py [--json] [--customer SLUG] [--dry-run]

Polls every customer's Orgo cloud computers and prints a structured
report. Exit code 0 = all healthy, 1 = at least one issue found,
2 = no customers configured.

The long-running equivalent is scripts/watchdog.py (or `make watchdog`).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import structlog  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.table import Table  # noqa: E402

from src.config import list_customers, load_customer, load_env  # noqa: E402
from src.observability import HealthCheck, Watchdog  # noqa: E402
from src.orgo_client import OrgoClient  # noqa: E402
from src.telegram_meta import TelegramMeta  # noqa: E402

log = structlog.get_logger(__name__)
console = Console()


# ---------------------------------------------------------------------------
# Status styling
# ---------------------------------------------------------------------------
STATUS_STYLE = {
    "healthy": ("[green]healthy[/green]", "✓"),
    "degraded": ("[yellow]degraded[/yellow]", "⚠"),
    "down": ("[red]down[/red]", "✗"),
    "unknown": ("[dim]unknown[/dim]", "?"),
}


def _styled_status(status: str) -> str:
    style, icon = STATUS_STYLE.get(status, ("[dim]???[/dim]", "?"))
    return f"{icon} {style}"


# ---------------------------------------------------------------------------
# Collect health checks
# ---------------------------------------------------------------------------
def run_health_checks(
    slugs: list[str],
    dry_run: bool = False,
) -> list[HealthCheck]:
    """Run a single-pass health check for the given customer slugs."""
    orgo = OrgoClient(dry_run=dry_run)
    telegram = TelegramMeta(dry_run=True)  # no alerts on one-shot check
    wd = Watchdog(orgo, telegram=telegram)

    results: list[HealthCheck] = []
    for slug in slugs:
        try:
            customer = load_customer(slug)
            checks = wd.check(customer)
            results.extend(checks)
        except FileNotFoundError:
            log.error("healthcheck.customer_not_found", slug=slug)
            results.append(
                HealthCheck(
                    customer_slug=slug,
                    agent_name="*",
                    cloud_computer_id="",
                    status="unknown",
                    last_heartbeat=None,
                    reason=f"config not found for '{slug}'",
                )
            )
        except Exception as exc:  # noqa: BLE001
            log.error("healthcheck.error", slug=slug, error=str(exc))
            results.append(
                HealthCheck(
                    customer_slug=slug,
                    agent_name="*",
                    cloud_computer_id="",
                    status="unknown",
                    last_heartbeat=None,
                    reason=str(exc),
                )
            )
    return results


# ---------------------------------------------------------------------------
# Output: Rich table
# ---------------------------------------------------------------------------
def print_table(results: list[HealthCheck], elapsed: float) -> None:
    table = Table(title="Agent Health Check", show_lines=False, padding=(0, 1))
    table.add_column("Customer", style="bold")
    table.add_column("Agent")
    table.add_column("Computer ID", style="dim")
    table.add_column("Status")
    table.add_column("Last Heartbeat")
    table.add_column("Reason", style="dim")

    for hc in sorted(results, key=lambda r: (r.customer_slug, r.agent_name)):
        heartbeat = (
            hc.last_heartbeat.strftime("%Y-%m-%d %H:%M:%S UTC")
            if hc.last_heartbeat
            else "—"
        )
        table.add_row(
            hc.customer_slug,
            hc.agent_name,
            hc.cloud_computer_id[:12] if hc.cloud_computer_id else "—",
            _styled_status(hc.status),
            heartbeat,
            hc.reason or "",
        )

    console.print()
    console.print(table)

    # Summary
    total = len(results)
    healthy = sum(1 for r in results if r.status == "healthy")
    degraded = sum(1 for r in results if r.status == "degraded")
    down = sum(1 for r in results if r.status == "down")
    unknown = sum(1 for r in results if r.status == "unknown")

    parts = [f"[bold]{total}[/bold] agents checked"]
    if healthy:
        parts.append(f"[green]{healthy} healthy[/green]")
    if degraded:
        parts.append(f"[yellow]{degraded} degraded[/yellow]")
    if down:
        parts.append(f"[red]{down} down[/red]")
    if unknown:
        parts.append(f"[dim]{unknown} unknown[/dim]")
    parts.append(f"in {elapsed:.1f}s")

    console.print()
    console.print(
        Panel(
            " · ".join(parts),
            title="Summary",
            border_style="green" if healthy == total else "red",
        )
    )


# ---------------------------------------------------------------------------
# Output: JSON
# ---------------------------------------------------------------------------
def _serialize_healthcheck(hc: HealthCheck) -> dict:
    d = asdict(hc)
    if d["last_heartbeat"]:
        d["last_heartbeat"] = d["last_heartbeat"].isoformat()
    return d


def print_json(results: list[HealthCheck], elapsed: float) -> None:
    now = datetime.now(timezone.utc)
    payload = {
        "timestamp": now.isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "total": len(results),
        "healthy": sum(1 for r in results if r.status == "healthy"),
        "degraded": sum(1 for r in results if r.status == "degraded"),
        "down": sum(1 for r in results if r.status == "down"),
        "unknown": sum(1 for r in results if r.status == "unknown"),
        "results": [_serialize_healthcheck(r) for r in results],
    }
    print(json.dumps(payload, indent=2))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="One-shot health check across all configured customers.",
    )
    p.add_argument(
        "--customer",
        "-c",
        help="Check a single customer by slug (default: all)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as JSON (for piping to monitoring tools)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Use dry-run Orgo client (no real API calls)",
    )
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    load_env()

    # Discover customers
    if args.customer:
        slugs = [args.customer]
    else:
        slugs = list_customers()

    if not slugs:
        if args.json_output:
            print(json.dumps({"error": "no customers configured", "results": []}))
        else:
            console.print(
                "[yellow]No customers found in config/customers/. "
                "Nothing to check.[/yellow]"
            )
        return 2

    # Run checks
    t0 = time.monotonic()
    results = run_health_checks(slugs, dry_run=args.dry_run)
    elapsed = time.monotonic() - t0

    # Output
    if args.json_output:
        print_json(results, elapsed)
    else:
        print_table(results, elapsed)

    # Exit code: 0 if all healthy, 1 if any issues
    all_ok = all(r.status == "healthy" for r in results)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
