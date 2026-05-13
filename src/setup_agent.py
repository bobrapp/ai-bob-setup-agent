"""ai-bob-setup-agent — main CLI entry point.

Usage:
    python -m src --doctor
    python -m src onboard --customer <slug> [--dry-run]
    python -m src add-agent --customer <slug> --agent <name> [--dry-run]
    python -m src decommission --customer <slug> [--dry-run]
    python -m src status --customer <slug>
    python -m src list
"""

from __future__ import annotations

import sys
import time

import click
import structlog
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import (
    REQUIRED_ENV_KEYS,
    CustomerConfig,
    StackConfig,
    check_env,
    list_customers,
    load_customer,
    load_env,
    validate_customer,
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


def _preflight(customer: CustomerConfig, *, strict: bool = False) -> bool:
    """Run pre-flight checks and print results. Returns True if safe to proceed."""
    result = validate_customer(customer)

    if result.errors:
        console.print()
        for err in result.errors:
            console.print(f"  [red]✗[/red] {err}")
    if result.warnings:
        console.print()
        for warn in result.warnings:
            console.print(f"  [yellow]![/yellow] {warn}")

    if result.ok and not result.warnings:
        console.print("  [green]✓[/green] All pre-flight checks passed.")

    if not result.ok:
        console.print(
            "\n[red bold]Pre-flight failed.[/red bold] "
            "Fix the errors above before onboarding."
        )
        return False

    if result.warnings and strict:
        console.print(
            "\n[yellow]Warnings present.[/yellow] "
            "Set missing keys in .env to silence them."
        )

    return True


def _estimate_cost(customer: CustomerConfig) -> int:
    """Estimate monthly cost based on agent tiers."""
    total = 0
    for agent in customer.agents:
        stack = StackConfig.load(agent.runtime)
        total += stack.monthly_price_usd
    return total


def _print_onboard_summary(
    customer: CustomerConfig,
    results: list[InstallResult],
    elapsed: float,
    dry_run: bool,
) -> None:
    """Print a rich summary panel after onboarding."""
    mode_label = "[yellow]DRY RUN[/yellow]" if dry_run else "[green]LIVE[/green]"

    # Agent results table
    table = Table(
        show_header=True,
        header_style="bold",
        title=f"Onboarding results — {customer.customer.slug}",
        title_style="bold",
        padding=(0, 1),
    )
    table.add_column("Agent", style="cyan")
    table.add_column("Runtime")
    table.add_column("MCPs", justify="right")
    table.add_column("Connectors", justify="right")
    table.add_column("2nd Brain")
    table.add_column("Computer ID", style="dim")

    for r in results:
        brain = "[green]✓[/green]" if r.second_brain_loaded else "[dim]—[/dim]"
        table.add_row(
            r.agent_name,
            r.runtime,
            str(len(r.mcps_installed)),
            str(len(r.connectors_installed)),
            brain,
            r.cloud_computer_id[:20] if r.cloud_computer_id else "—",
        )

    console.print()
    console.print(table)

    # Cost summary
    monthly = _estimate_cost(customer)
    cost_text = f"${monthly:,}/mo"

    # Footer panel
    lines = [
        f"Mode:      {mode_label}",
        f"Customer:  [bold]{customer.customer.legal_name}[/bold] ({customer.customer.slug})",
        f"Vertical:  {customer.customer.vertical}",
        f"Agents:    {len(results)}",
        f"Tier mix:  {', '.join(sorted({a.runtime for a in customer.agents}))}",
        f"Est. cost: [bold]{cost_text}[/bold]",
        f"Time:      {elapsed:.1f}s",
    ]
    console.print(
        Panel(
            "\n".join(lines),
            title="[bold green]✓ Onboarding complete[/bold green]"
            if not dry_run
            else "[bold yellow]✓ Dry run complete[/bold yellow]",
            border_style="green" if not dry_run else "yellow",
            padding=(1, 2),
        )
    )


def onboard_customer(customer: CustomerConfig, dry_run: bool) -> list[InstallResult]:
    """Run the full onboarding ritual end-to-end."""
    log.info(
        "onboard.start", customer=customer.customer.slug, agents=len(customer.agents)
    )

    # Pre-flight
    console.print(
        Panel(
            f"[bold]{customer.customer.legal_name}[/bold] "
            f"({customer.customer.slug})\n"
            f"{len(customer.agents)} agent(s) · "
            f"{customer.contract.tier} tier · "
            f"{customer.customer.vertical}",
            title="[bold]Onboarding[/bold]",
            border_style="blue",
        )
    )
    console.print("\n[bold]Pre-flight checks[/bold]")
    if not _preflight(customer):
        raise click.Abort()

    t0 = time.monotonic()
    orgo = _make_orgo(dry_run)
    telegram = _make_telegram(dry_run)
    installer = HermesInstaller(orgo, dry_run=dry_run)

    # Step 1: Workspace
    console.print("\n[bold]Step 1/4[/bold] — Provisioning workspace…")
    workspace = orgo.ensure_workspace(
        customer.customer.slug, customer.customer.timezone
    )
    console.print(
        f"  [green]✓[/green] Workspace [cyan]{workspace.id}[/cyan] (region={workspace.region})"
    )
    log.info("onboard.workspace_ready", workspace_id=workspace.id)

    # Step 2: Cloud computers + runtime install
    results: list[InstallResult] = []
    for i, agent in enumerate(customer.agents, 1):
        console.print(
            f"\n[bold]Step 2/4[/bold] — Agent {i}/{len(customer.agents)}: "
            f"[cyan]{agent.name}[/cyan] ({agent.runtime})"
        )
        stack = StackConfig.load(agent.runtime)

        console.print(
            f"  Provisioning cloud computer ({stack.resources.cpu_vcpus} vCPU, "
            f"{stack.resources.memory_gb} GB RAM, {stack.resources.disk_gb} GB disk)…"
        )
        cc = orgo.ensure_cloud_computer(
            workspace_id=workspace.id,
            agent_name=agent.name,
            image=stack.runtime["base_image"],
            cpu_vcpus=stack.resources.cpu_vcpus,
            memory_gb=stack.resources.memory_gb,
            disk_gb=stack.resources.disk_gb,
        )
        console.print(f"  [green]✓[/green] Cloud computer [cyan]{cc.id}[/cyan]")

        console.print(
            f"  Installing {stack.stack} runtime + {len(agent.mcps)} MCPs "
            f"+ {len(agent.connectors)} connectors…"
        )
        result = installer.install(cc, agent, stack)
        results.append(result)

        parts = []
        if result.mcps_installed:
            parts.append(f"MCPs: {', '.join(result.mcps_installed)}")
        if result.connectors_installed:
            parts.append(f"Connectors: {', '.join(result.connectors_installed)}")
        if result.second_brain_loaded:
            parts.append("Second brain: loaded")
        console.print(f"  [green]✓[/green] {' · '.join(parts) or 'Installed'}")

    # Step 3: Notify
    console.print("\n[bold]Step 3/4[/bold] — Sending notifications…")
    telegram.notify_provisioned(
        customer.customer.slug, [a.name for a in customer.agents]
    )
    console.print("  [green]✓[/green] Telegram notification sent")

    # Step 4: Summary
    elapsed = time.monotonic() - t0
    console.print("\n[bold]Step 4/4[/bold] — Summary")
    _print_onboard_summary(customer, results, elapsed, dry_run)

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

    console.print(
        f"\n[bold]Adding agent[/bold] [cyan]{agent_name}[/cyan] "
        f"to [bold]{customer.customer.slug}[/bold]…"
    )
    cc = orgo.ensure_cloud_computer(
        workspace_id=workspace.id,
        agent_name=agent.name,
        image=stack.runtime["base_image"],
        cpu_vcpus=stack.resources.cpu_vcpus,
        memory_gb=stack.resources.memory_gb,
        disk_gb=stack.resources.disk_gb,
    )
    result = installer.install(cc, agent, stack)
    console.print(
        f"[green]✓[/green] {result.agent_name} ({result.runtime}) — "
        f"{len(result.mcps_installed)} MCPs, "
        f"{len(result.connectors_installed)} connectors"
    )
    return result


def decommission_customer(customer: CustomerConfig, dry_run: bool) -> None:
    orgo = _make_orgo(dry_run)
    telegram = _make_telegram(dry_run)

    console.print(
        f"\n[bold red]Decommissioning[/bold red] [bold]{customer.customer.slug}[/bold]…"
    )
    workspace = orgo.get_workspace_by_slug(customer.customer.slug)
    if not workspace:
        console.print("  [yellow]No workspace found — nothing to tear down.[/yellow]")
        log.info("decom.no_workspace", customer=customer.customer.slug)
        return
    computers = orgo.list_cloud_computers(workspace.id)
    for cc in computers:
        console.print(
            f"  Deleting cloud computer [cyan]{cc.id}[/cyan] ({cc.agent_name})…"
        )
        orgo.delete_cloud_computer(workspace.id, cc.id)
    orgo.delete_workspace(workspace.id)
    telegram.notify_decommissioned(customer.customer.slug)
    console.print(
        f"  [green]✓[/green] Workspace torn down. {len(computers)} computer(s) removed."
    )


def show_status(customer: CustomerConfig, dry_run: bool) -> None:
    """Show the deployment status of a customer's agents."""
    orgo = _make_orgo(dry_run)
    workspace = orgo.get_workspace_by_slug(customer.customer.slug)

    table = Table(
        title=f"Status — {customer.customer.legal_name} ({customer.customer.slug})",
        show_header=True,
        header_style="bold",
    )
    table.add_column("Agent", style="cyan")
    table.add_column("Runtime")
    table.add_column("Status")
    table.add_column("Computer ID", style="dim")
    table.add_column("Endpoint")

    if not workspace:
        for agent in customer.agents:
            table.add_row(
                agent.name,
                agent.runtime,
                "[red]not provisioned[/red]",
                "—",
                "—",
            )
    else:
        computers_by_name = {
            cc.agent_name: cc for cc in orgo.list_cloud_computers(workspace.id)
        }
        for agent in customer.agents:
            cc = computers_by_name.get(agent.name)
            if cc:
                colour = {
                    "running": "green",
                    "provisioning": "yellow",
                    "stopped": "red",
                    "error": "red",
                }.get(cc.status, "magenta")
                table.add_row(
                    agent.name,
                    agent.runtime,
                    f"[{colour}]{cc.status}[/{colour}]",
                    cc.id[:20],
                    cc.public_endpoint or "—",
                )
            else:
                table.add_row(
                    agent.name,
                    agent.runtime,
                    "[red]not provisioned[/red]",
                    "—",
                    "—",
                )

    console.print()
    console.print(table)

    # Cost line
    monthly = _estimate_cost(customer)
    console.print(f"\n  Est. monthly cost: [bold]${monthly:,}[/bold]")


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
    table.add_column("Est. cost")
    for slug in slugs:
        c = load_customer(slug)
        monthly = _estimate_cost(c)
        table.add_row(
            slug,
            c.customer.legal_name,
            c.contract.tier,
            str(len(c.agents)),
            f"${monthly:,}/mo",
        )
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
    onboard_customer(c, dry_run=dr)


@cli.command("add-agent")
@click.option("--customer", required=True)
@click.option("--agent", required=True)
@click.option("--dry-run", default=False)
def cmd_add_agent(customer: str, agent: str, dry_run: str | bool) -> None:
    """Add a new agent to an existing customer."""
    dr = _dry_run_flag(dry_run)
    c = load_customer(customer)
    add_agent_to_customer(c, agent, dry_run=dr)


@cli.command("decommission")
@click.option("--customer", required=True)
@click.option("--dry-run", default=False)
def cmd_decom(customer: str, dry_run: str | bool) -> None:
    """Decommission a customer (remove all agents and workspace)."""
    dr = _dry_run_flag(dry_run)
    c = load_customer(customer)
    decommission_customer(c, dry_run=dr)


@cli.command("status")
@click.option("--customer", required=True, help="Customer slug")
@click.option("--dry-run", default=False)
def cmd_status(customer: str, dry_run: str | bool) -> None:
    """Show current deployment status for a customer's agents."""
    dr = _dry_run_flag(dry_run)
    c = load_customer(customer)
    show_status(c, dry_run=dr)


@cli.command("validate")
@click.option("--customer", required=True, help="Customer slug")
def cmd_validate(customer: str) -> None:
    """Validate a customer config without running any operations."""
    c = load_customer(customer)
    console.print(
        f"\n[bold]Validating[/bold] {c.customer.legal_name} ({c.customer.slug})"
    )
    ok = _preflight(c)
    if ok:
        monthly = _estimate_cost(c)
        console.print(
            f"\n  {len(c.agents)} agent(s) · "
            f"est. [bold]${monthly:,}/mo[/bold] · ready to onboard"
        )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    cli()
