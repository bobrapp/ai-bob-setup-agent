"""ai-bob-setup-agent — main CLI entry point.

Usage:
    python -m src.setup_agent --doctor
    python -m src.setup_agent onboard --customer <slug> [--dry-run]
    python -m src.setup_agent add-agent --customer <slug> --agent <name> [--dry-run]
    python -m src.setup_agent decommission --customer <slug> [--dry-run]
    python -m src.setup_agent list
"""

from __future__ import annotations

import sys

import click
import structlog
from rich.console import Console
from rich.table import Table

from .config import (
    REQUIRED_ENV_KEYS,
    CustomerConfig,
    StackConfig,
    check_env,
    list_customers,
    load_customer,
    load_env,
)
from .hermes_install import HermesInstaller, InstallResult
from .orgo_client import OrgoClient
from .telegram_meta import TelegramMeta

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
)

log = structlog.get_logger(__name__)
console = Console()


# ---------------------------------------------------------------------------
# Core orchestration
# ---------------------------------------------------------------------------
def _make_orgo(dry_run: bool) -> OrgoClient:
    load_env()
    return OrgoClient(dry_run=dry_run)


def _make_telegram(dry_run: bool) -> TelegramMeta:
    load_env()
    return TelegramMeta(dry_run=dry_run)


def onboard_customer(customer: CustomerConfig, dry_run: bool) -> list[InstallResult]:
    """Run the full onboarding ritual end-to-end."""
    log.info(
        "onboard.start", customer=customer.customer.slug, agents=len(customer.agents)
    )
    orgo = _make_orgo(dry_run)
    telegram = _make_telegram(dry_run)
    installer = HermesInstaller(orgo, dry_run=dry_run)

    workspace = orgo.ensure_workspace(
        customer.customer.slug, customer.customer.timezone
    )
    log.info("onboard.workspace_ready", workspace_id=workspace.id)

    results: list[InstallResult] = []
    for agent in customer.agents:
        stack = StackConfig.load(agent.runtime)
        cc = orgo.ensure_cloud_computer(
            workspace_id=workspace.id,
            agent_name=agent.name,
            image=stack.runtime["base_image"],
            cpu_vcpus=stack.resources.cpu_vcpus,
            memory_gb=stack.resources.memory_gb,
            disk_gb=stack.resources.disk_gb,
        )
        results.append(installer.install(cc, agent, stack))

    telegram.notify_provisioned(
        customer.customer.slug, [a.name for a in customer.agents]
    )
    log.info("onboard.done", customer=customer.customer.slug, agent_count=len(results))
    return results


def add_agent_to_customer(
    customer: CustomerConfig,
    agent_name: str,
    dry_run: bool,
) -> InstallResult:
    agent = next((a for a in customer.agents if a.name == agent_name), None)
    if not agent:
        raise click.ClickException(
            f"Agent '{agent_name}' not in customer config. Add it to the YAML first."
        )
    orgo = _make_orgo(dry_run)
    installer = HermesInstaller(orgo, dry_run=dry_run)
    workspace = orgo.ensure_workspace(
        customer.customer.slug, customer.customer.timezone
    )
    stack = StackConfig.load(agent.runtime)
    cc = orgo.ensure_cloud_computer(
        workspace_id=workspace.id,
        agent_name=agent.name,
        image=stack.runtime["base_image"],
        cpu_vcpus=stack.resources.cpu_vcpus,
        memory_gb=stack.resources.memory_gb,
        disk_gb=stack.resources.disk_gb,
    )
    return installer.install(cc, agent, stack)


def decommission_customer(customer: CustomerConfig, dry_run: bool) -> None:
    orgo = _make_orgo(dry_run)
    telegram = _make_telegram(dry_run)
    workspace = orgo.get_workspace_by_slug(customer.customer.slug)
    if not workspace:
        log.info("decom.no_workspace", customer=customer.customer.slug)
        return
    for cc in orgo.list_cloud_computers(workspace.id):
        orgo.delete_cloud_computer(workspace.id, cc.id)
    orgo.delete_workspace(workspace.id)
    telegram.notify_decommissioned(customer.customer.slug)


# ---------------------------------------------------------------------------
# Doctor
# ---------------------------------------------------------------------------
def run_doctor() -> int:
    """Verify environment readiness. Returns exit code."""
    load_env()
    missing = check_env()
    table = Table(
        title="Environment doctor", show_header=True, header_style="bold cyan"
    )
    table.add_column("Key")
    table.add_column("Status")
    table.add_column("Severity")
    for key in REQUIRED_ENV_KEYS:
        status = "MISSING" if key in missing["required"] else "ok"
        sev = "required" if status == "MISSING" else ""
        table.add_row(key, status, sev)
    for key in missing["optional"]:
        table.add_row(key, "missing", "optional")
    console.print(table)

    # Try orgo ping if key is present
    import os

    if os.getenv("ORGO_API_KEY"):
        try:
            orgo = OrgoClient(dry_run=False)
            reachable = orgo.ping()
            console.print(
                "[green]Orgo API reachable[/green]"
                if reachable
                else "[yellow]Orgo API unreachable[/yellow]"
            )
        except Exception as exc:  # noqa: BLE001
            console.print(f"[yellow]Orgo client init failed: {exc}[/yellow]")
    if missing["required"]:
        console.print(
            "[red]Required keys missing. Fill in .env before running real operations.[/red]"
        )
        return 1
    console.print("[green]Doctor: OK[/green]")
    return 0


# ---------------------------------------------------------------------------
# Click CLI
# ---------------------------------------------------------------------------
@click.group(invoke_without_command=True)
@click.option(
    "--doctor", "doctor_only", is_flag=True, help="Run environment doctor and exit"
)
@click.pass_context
def cli(ctx: click.Context, doctor_only: bool) -> None:
    if doctor_only:
        sys.exit(run_doctor())
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command("list")
def cmd_list() -> None:
    """List all configured customers."""
    slugs = list_customers()
    if not slugs:
        console.print(
            "[yellow]No customers configured.[/yellow] Add YAML files to config/customers/"
        )
        return
    table = Table(title="Customers")
    table.add_column("Slug")
    table.add_column("Legal name")
    table.add_column("Tier")
    table.add_column("Agents")
    for slug in slugs:
        c = load_customer(slug)
        table.add_row(slug, c.customer.legal_name, c.contract.tier, str(len(c.agents)))
    console.print(table)


def _dry_run_flag(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"true", "1", "yes", "y"}


@cli.command("onboard")
@click.option("--customer", required=True, help="Customer slug")
@click.option("--dry-run", default=False, help="Log intended actions without executing")
def cmd_onboard(customer: str, dry_run: str | bool) -> None:
    """Run full onboarding for a customer."""
    dr = _dry_run_flag(dry_run)
    c = load_customer(customer)
    results = onboard_customer(c, dry_run=dr)
    console.print(f"[green]Onboarded[/green] {customer} ({len(results)} agents)")
    for r in results:
        console.print(
            f"  • {r.agent_name} on {r.runtime} "
            f"({len(r.mcps_installed)} MCPs, {len(r.connectors_installed)} connectors)"
        )


@cli.command("add-agent")
@click.option("--customer", required=True)
@click.option("--agent", required=True)
@click.option("--dry-run", default=False)
def cmd_add_agent(customer: str, agent: str, dry_run: str | bool) -> None:
    dr = _dry_run_flag(dry_run)
    c = load_customer(customer)
    r = add_agent_to_customer(c, agent, dry_run=dr)
    console.print(f"[green]Added[/green] {r.agent_name} ({r.runtime}) to {customer}")


@cli.command("decommission")
@click.option("--customer", required=True)
@click.option("--dry-run", default=False)
def cmd_decom(customer: str, dry_run: str | bool) -> None:
    dr = _dry_run_flag(dry_run)
    c = load_customer(customer)
    decommission_customer(c, dry_run=dr)
    console.print(f"[green]Decommissioned[/green] {customer}")


if __name__ == "__main__":
    cli()
