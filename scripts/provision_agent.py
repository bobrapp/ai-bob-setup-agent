#!/usr/bin/env python3
"""Provision a single agent inside an existing customer workspace."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import click  # noqa: E402

from src.config import load_customer, load_env  # noqa: E402
from src.setup_agent import add_agent_to_customer  # noqa: E402


@click.command()
@click.option("--customer", required=True, help="Customer slug")
@click.option("--agent", required=True, help="Agent name (must exist in customer YAML)")
@click.option("--dry-run", is_flag=True, default=False)
def main(customer: str, agent: str, dry_run: bool) -> None:
    load_env()
    c = load_customer(customer)
    result = add_agent_to_customer(c, agent, dry_run=dry_run)
    click.echo(
        f"Provisioned {result.agent_name} ({result.runtime}) — "
        f"MCPs: {result.mcps_installed}, connectors: {result.connectors_installed}"
    )


if __name__ == "__main__":
    main()
