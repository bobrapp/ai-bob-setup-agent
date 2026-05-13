#!/usr/bin/env python3
"""Provision a single workspace for a customer.

Standalone counterpart to `python -m src.setup_agent onboard`. Useful when
you want to create the workspace but defer agent provisioning.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import click  # noqa: E402

from src.config import load_customer, load_env  # noqa: E402
from src.orgo_client import OrgoClient  # noqa: E402


@click.command()
@click.option("--customer", required=True, help="Customer slug")
@click.option("--dry-run", is_flag=True, default=False)
def main(customer: str, dry_run: bool) -> None:
    load_env()
    c = load_customer(customer)
    orgo = OrgoClient(dry_run=dry_run)
    ws = orgo.ensure_workspace(c.customer.slug, c.customer.timezone)
    click.echo(f"Workspace ready: {ws.id} (region={ws.region})")


if __name__ == "__main__":
    main()
