"""ai-bob-setup-agent — main CLI entry point.

Usage:
    python -m src --doctor
    python -m src onboard --customer <slug> [--dry-run]
    python -m src add-agent --customer <slug> --agent <name> [--dry-run]
    python -m src decommission --customer <slug> [--dry-run] [--force]
    python -m src status --customer <slug>
    python -m src list
    python -m src audit [--limit N]
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field

import click
import structlog
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .audit_log import log_action, print_log
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
# Data models
# ---------------------------------------------------------------------------
@dataclass
class DecomResult:
    """Structured result from decommissioning a customer."""

    customer_slug: str
    workspace_id: str
    computers_deleted: list[str] = field(default_factory=list)
    workspace_deleted: bool = False
    notification_sent: bool = False
    dry_run: bool = False
    elapsed: float = 0.0

    @property
    def total_deleted(self) -> int:
        return len(self.computers_deleted)


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
    """Add a single agent to an existing customer workspace.

    Validates the agent exists in the YAML config, checks it's not already
    provisioned, provisions the cloud computer, installs the runtime, and
    sends a notification. Returns the structured InstallResult.
    """
    slug = customer.customer.slug
    mode_label = "[yellow]DRY RUN[/yellow]" if dry_run else "[green]LIVE[/green]"
    log.info("add_agent.start", customer=slug, agent=agent_name, dry_run=dry_run)

    # Step 1: Validate agent exists in config
    console.print(
        Panel(
            f"[bold]{customer.customer.legal_name}[/bold] ({slug})\n"
            f"Agent: [cyan]{agent_name}[/cyan]\n"
            f"Mode: {mode_label}",
            title="[bold]Add Agent[/bold]",
            border_style="blue",
        )
    )

    console.print("\n[bold]Step 1/5[/bold] — Validating agent config…")
    agent = next((a for a in customer.agents if a.name == agent_name), None)
    if not agent:
        available = [a.name for a in customer.agents]
        console.print(f"  [red]✗[/red] Agent '{agent_name}' not in customer config.")
        console.print(f"  Available agents: {', '.join(available)}")
        console.print("  Add the agent to the YAML file first, then retry.")
        raise click.ClickException(
            f"Agent '{agent_name}' not in config. Available: {', '.join(available)}"
        )

    stack = StackConfig.load(agent.runtime)
    agent_cost = stack.monthly_price_usd

    # Show agent details
    details_table = Table(show_header=False, box=None, padding=(0, 2), show_edge=False)
    details_table.add_column("Field", style="dim")
    details_table.add_column("Value")
    details_table.add_row("Runtime", f"{agent.runtime} (${agent_cost:,}/mo)")
    details_table.add_row(
        "Resources",
        f"{stack.resources.cpu_vcpus} vCPU · "
        f"{stack.resources.memory_gb} GB RAM · "
        f"{stack.resources.disk_gb} GB disk",
    )
    details_table.add_row("MCPs", ", ".join(agent.mcps) if agent.mcps else "—")
    details_table.add_row(
        "Connectors", ", ".join(agent.connectors) if agent.connectors else "—"
    )
    details_table.add_row(
        "Composio apps",
        ", ".join(agent.composio_apps) if agent.composio_apps else "—",
    )
    details_table.add_row(
        "Second brain",
        "[green]enabled[/green]" if agent.second_brain.enabled else "[dim]off[/dim]",
    )
    console.print(details_table)
    console.print("  [green]✓[/green] Agent config valid")

    # Step 2: Pre-flight (light check — just env keys)
    console.print("\n[bold]Step 2/5[/bold] — Pre-flight checks…")
    if not _preflight(customer):
        raise click.Abort()

    t0 = time.monotonic()
    orgo = _make_orgo(dry_run)
    telegram = _make_telegram(dry_run)
    installer = HermesInstaller(orgo, dry_run=dry_run)

    # Step 3: Ensure workspace + check for duplicates
    console.print("\n[bold]Step 3/5[/bold] — Ensuring workspace…")
    workspace = orgo.ensure_workspace(slug, customer.customer.timezone)
    console.print(
        f"  [green]✓[/green] Workspace [cyan]{workspace.id}[/cyan] "
        f"(region={workspace.region})"
    )

    # Check if agent is already provisioned
    existing_computers = orgo.list_cloud_computers(workspace.id)
    existing_names = {cc.agent_name for cc in existing_computers}
    if agent_name in existing_names and not dry_run:
        console.print(
            f"  [yellow]![/yellow] Agent '{agent_name}' already has a cloud "
            f"computer. Re-running will converge to the same state (idempotent)."
        )

    # Step 4: Provision + install
    console.print(f"\n[bold]Step 4/5[/bold] — Provisioning [cyan]{agent_name}[/cyan]…")
    console.print(
        f"  Creating cloud computer ({stack.resources.cpu_vcpus} vCPU, "
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
        f"  Installing {stack.stack} runtime + "
        f"{len(agent.mcps)} MCPs + {len(agent.connectors)} connectors…"
    )
    result = installer.install(cc, agent, stack)

    parts = []
    if result.mcps_installed:
        parts.append(f"MCPs: {', '.join(result.mcps_installed)}")
    if result.connectors_installed:
        parts.append(f"Connectors: {', '.join(result.connectors_installed)}")
    if result.second_brain_loaded:
        parts.append("Second brain: loaded")
    console.print(f"  [green]✓[/green] {' · '.join(parts) or 'Installed'}")

    # Step 5: Notify + summary
    console.print("\n[bold]Step 5/5[/bold] — Notification and summary…")
    telegram.notify_provisioned(slug, [agent_name])
    console.print("  [green]✓[/green] Telegram notification sent")

    elapsed = time.monotonic() - t0

    # Cost impact
    old_cost = sum(
        StackConfig.load(a.runtime).monthly_price_usd
        for a in customer.agents
        if a.name != agent_name
    )
    new_cost = old_cost + agent_cost

    # Summary panel
    lines = [
        f"Mode:       {mode_label}",
        f"Customer:   [bold]{customer.customer.legal_name}[/bold] ({slug})",
        f"Agent:      [cyan]{result.agent_name}[/cyan] ({result.runtime})",
        f"Computer:   [dim]{result.cloud_computer_id}[/dim]",
        f"MCPs:       {len(result.mcps_installed)}",
        f"Connectors: {len(result.connectors_installed)}",
        f"2nd brain:  {'[green]✓[/green]' if result.second_brain_loaded else '[dim]—[/dim]'}",
        f"Cost delta: [bold]${old_cost:,} → ${new_cost:,}/mo[/bold] (+${agent_cost:,})",
        f"Time:       {elapsed:.1f}s",
    ]
    console.print()
    console.print(
        Panel(
            "\n".join(lines),
            title="[bold green]✓ Agent added[/bold green]"
            if not dry_run
            else "[bold yellow]✓ Dry run complete[/bold yellow]",
            border_style="green" if not dry_run else "yellow",
            padding=(1, 2),
        )
    )

    log.info(
        "add_agent.done",
        customer=slug,
        agent=agent_name,
        runtime=result.runtime,
        mcps=len(result.mcps_installed),
        elapsed=round(elapsed, 1),
    )
    return result


def decommission_customer(
    customer: CustomerConfig,
    dry_run: bool,
    force: bool = False,
) -> DecomResult:
    """Tear down all cloud computers and the workspace for a customer.

    Returns a DecomResult with details of what was removed. In interactive
    mode (force=False), prompts for confirmation before proceeding.
    """
    slug = customer.customer.slug
    log.info("decom.start", customer=slug, dry_run=dry_run)

    mode_label = "[yellow]DRY RUN[/yellow]" if dry_run else "[red]LIVE[/red]"
    monthly = _estimate_cost(customer)

    # Header panel
    console.print(
        Panel(
            f"[bold]{customer.customer.legal_name}[/bold] ({slug})\n"
            f"{len(customer.agents)} agent(s) · "
            f"{customer.contract.tier} tier · "
            f"${monthly:,}/mo\n"
            f"Mode: {mode_label}",
            title="[bold red]⚠ Decommission[/bold red]",
            border_style="red",
        )
    )

    orgo = _make_orgo(dry_run)
    telegram = _make_telegram(dry_run)

    # Step 1: Discover workspace
    console.print("\n[bold]Step 1/4[/bold] — Discovering workspace…")
    workspace = orgo.get_workspace_by_slug(slug)
    if not workspace:
        console.print("  [yellow]No workspace found — nothing to tear down.[/yellow]")
        log.info("decom.no_workspace", customer=slug)
        return DecomResult(
            customer_slug=slug,
            workspace_id="",
            dry_run=dry_run,
        )

    computers = orgo.list_cloud_computers(workspace.id)
    console.print(
        f"  [green]✓[/green] Workspace [cyan]{workspace.id}[/cyan] "
        f"with {len(computers)} cloud computer(s)"
    )

    # Show what will be destroyed
    if computers:
        destroy_table = Table(
            title="Resources to destroy",
            show_header=True,
            header_style="bold red",
            padding=(0, 1),
        )
        destroy_table.add_column("Resource")
        destroy_table.add_column("ID", style="dim")
        destroy_table.add_column("Agent")
        destroy_table.add_column("Status")

        for cc in computers:
            colour = {
                "running": "green",
                "provisioning": "yellow",
                "stopped": "red",
                "error": "red",
            }.get(cc.status, "magenta")
            destroy_table.add_row(
                "Cloud Computer",
                cc.id[:20],
                cc.agent_name,
                f"[{colour}]{cc.status}[/{colour}]",
            )
        destroy_table.add_row(
            "Workspace", workspace.id[:20], "—", "[dim]container[/dim]"
        )
        console.print()
        console.print(destroy_table)

    # Step 2: Confirmation
    console.print("\n[bold]Step 2/4[/bold] — Confirmation…")
    if not force and not dry_run:
        console.print()
        console.print(
            "  [red bold]This action is irreversible.[/red bold] "
            f"All {len(computers)} cloud computer(s) and the workspace "
            "will be permanently deleted."
        )
        confirm = click.confirm(
            f"  Proceed with decommissioning '{slug}'?", default=False
        )
        if not confirm:
            console.print("  [yellow]Aborted.[/yellow]")
            log.info("decom.aborted", customer=slug)
            return DecomResult(
                customer_slug=slug,
                workspace_id=workspace.id,
                dry_run=dry_run,
            )
    elif dry_run:
        console.print("  [yellow]Skipped (dry run)[/yellow]")
    else:
        console.print("  [dim]Skipped (--force)[/dim]")

    t0 = time.monotonic()
    result = DecomResult(
        customer_slug=slug,
        workspace_id=workspace.id,
        dry_run=dry_run,
    )

    # Step 3: Delete cloud computers
    console.print(
        f"\n[bold]Step 3/4[/bold] — Deleting {len(computers)} cloud computer(s)…"
    )
    for i, cc in enumerate(computers, 1):
        console.print(
            f"  [{i}/{len(computers)}] Deleting [cyan]{cc.agent_name}[/cyan] "
            f"({cc.id[:16]})…"
        )
        try:
            orgo.delete_cloud_computer(workspace.id, cc.id)
            result.computers_deleted.append(cc.agent_name)
            console.print("       [green]✓[/green] Deleted")
        except Exception as exc:  # noqa: BLE001
            console.print(f"       [red]✗[/red] Failed: {exc}")
            log.error(
                "decom.delete_computer_failed",
                computer_id=cc.id,
                agent=cc.agent_name,
                error=str(exc),
            )

    # Delete workspace
    console.print(f"\n  Deleting workspace [cyan]{workspace.id}[/cyan]…")
    try:
        orgo.delete_workspace(workspace.id)
        result.workspace_deleted = True
        console.print("  [green]✓[/green] Workspace deleted")
    except Exception as exc:  # noqa: BLE001
        console.print(f"  [red]✗[/red] Failed: {exc}")
        log.error(
            "decom.delete_workspace_failed",
            workspace_id=workspace.id,
            error=str(exc),
        )

    # Step 4: Notifications and summary
    console.print("\n[bold]Step 4/4[/bold] — Notifications and summary…")
    result.notification_sent = telegram.notify_decommissioned(slug)
    if result.notification_sent:
        console.print("  [green]✓[/green] Farewell notification sent via Telegram")
    else:
        console.print("  [yellow]![/yellow] Telegram notification not sent")

    result.elapsed = time.monotonic() - t0

    # Summary panel
    _print_decom_summary(customer, result)

    log.info(
        "decom.done",
        customer=slug,
        computers_deleted=result.total_deleted,
        workspace_deleted=result.workspace_deleted,
        elapsed=round(result.elapsed, 1),
    )
    return result


def _print_decom_summary(customer: CustomerConfig, result: DecomResult) -> None:
    """Print a rich summary panel after decommissioning."""
    mode_label = "[yellow]DRY RUN[/yellow]" if result.dry_run else "[red]LIVE[/red]"
    monthly_saved = _estimate_cost(customer)

    lines = [
        f"Mode:              {mode_label}",
        f"Customer:          [bold]{customer.customer.legal_name}[/bold] ({result.customer_slug})",
        f"Computers deleted: [bold]{result.total_deleted}[/bold]/{len(customer.agents)}",
        f"Workspace deleted: {'[green]yes[/green]' if result.workspace_deleted else '[red]no[/red]'}",
        f"Notification sent: {'[green]yes[/green]' if result.notification_sent else '[yellow]no[/yellow]'}",
        f"Monthly savings:   [bold green]${monthly_saved:,}/mo[/bold green]",
        f"Time:              {result.elapsed:.1f}s",
    ]

    all_ok = result.total_deleted == len(customer.agents) and result.workspace_deleted
    title = (
        "[bold green]✓ Decommission complete[/bold green]"
        if all_ok
        else "[bold yellow]⚠ Decommission partial[/bold yellow]"
    )
    border = "green" if all_ok else "yellow"

    console.print()
    console.print(
        Panel(
            "\n".join(lines),
            title=title,
            border_style=border,
            padding=(1, 2),
        )
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
    log_action(
        action="onboard",
        command=f"onboard --customer {customer} --dry-run={dr}",
        customer=customer,
        dry_run=dr,
        status="started",
        result_summary=f"Onboarding {customer} ({len(c.agents)} agents)",
    )
    results = onboard_customer(c, dry_run=dr)
    log_action(
        action="onboard",
        command=f"onboard --customer {customer} --dry-run={dr}",
        customer=customer,
        dry_run=dr,
        status="success",
        result_summary=f"Onboarded {len(results)} agents for {customer}",
        details={"agents": [r.agent_name for r in results]},
    )


@cli.command("add-agent")
@click.option("--customer", required=True)
@click.option("--agent", required=True)
@click.option("--dry-run", default=False)
def cmd_add_agent(customer: str, agent: str, dry_run: str | bool) -> None:
    """Add a new agent to an existing customer."""
    dr = _dry_run_flag(dry_run)
    c = load_customer(customer)
    result = add_agent_to_customer(c, agent, dry_run=dr)
    log_action(
        action="add-agent",
        command=f"add-agent --customer {customer} --agent {agent} --dry-run={dr}",
        customer=customer,
        dry_run=dr,
        status="success",
        result_summary=f"Added {result.agent_name} ({result.runtime}) to {customer}",
        details={
            "agent": result.agent_name,
            "runtime": result.runtime,
            "mcps": result.mcps_installed,
        },
    )


@cli.command("decommission")
@click.option("--customer", required=True)
@click.option("--dry-run", default=False)
@click.option("--force", is_flag=True, default=False, help="Skip confirmation prompt")
def cmd_decom(customer: str, dry_run: str | bool, force: bool) -> None:
    """Decommission a customer (remove all agents and workspace)."""
    dr = _dry_run_flag(dry_run)
    c = load_customer(customer)
    result = decommission_customer(c, dry_run=dr, force=force)
    log_action(
        action="decommission",
        command=f"decommission --customer {customer} --dry-run={dr} --force={force}",
        customer=customer,
        dry_run=dr,
        status="success" if result.workspace_deleted else "partial",
        result_summary=(
            f"Decommissioned {customer}: {result.total_deleted} computers deleted"
        ),
        details={
            "computers_deleted": result.computers_deleted,
            "workspace_deleted": result.workspace_deleted,
        },
    )
    # Exit non-zero if teardown was incomplete
    if result.workspace_id and not result.workspace_deleted:
        sys.exit(1)


@cli.command("status")
@click.option("--customer", required=True, help="Customer slug")
@click.option("--dry-run", default=False)
def cmd_status(customer: str, dry_run: str | bool) -> None:
    """Show current deployment status for a customer's agents."""
    dr = _dry_run_flag(dry_run)
    c = load_customer(customer)
    show_status(c, dry_run=dr)
    log_action(
        action="status",
        command=f"status --customer {customer}",
        customer=customer,
        dry_run=dr,
        status="success",
        result_summary=f"Status checked for {customer}",
    )


@cli.command("audit")
@click.option("--limit", default=20, help="Number of entries to show")
def cmd_audit(limit: int) -> None:
    """Show the AIGovOps audit log."""
    print_log(limit)


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
