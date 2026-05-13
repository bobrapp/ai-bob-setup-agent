#!/usr/bin/env python3
"""Generate dashboard-data.json from customer configs and stack pricing.

Reads:
  config/customers/*.yaml   — customer configurations (gitignored)
  config/stacks/*.yaml      — stack/tier definitions with pricing

Writes:
  dashboard-data.json       — safe-to-commit JSON consumed by dashboard.html

The output contains NO secrets (no emails, phones, API keys).
Run this locally whenever customer configs change, then commit the JSON.

Usage:
    python scripts/generate_dashboard_data.py
    python -m scripts.generate_dashboard_data          # if running as module
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running from repo root or scripts/
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.config import StackConfig, list_customers, load_customer  # noqa: E402


def generate() -> dict:
    """Build the dashboard data structure from live configs."""

    # Load stack pricing
    stacks: dict[str, int] = {}
    for tier in ("hermes", "openclaw"):
        try:
            stack = StackConfig.load(tier)
            stacks[tier] = stack.monthly_price_usd
        except FileNotFoundError:
            print(f"Warning: stack definition for '{tier}' not found, using default")
            stacks[tier] = 10_000 if tier == "hermes" else 5_000

    # Discover and load customers
    slugs = list_customers()
    if not slugs:
        print("No customer configs found in config/customers/")
        print("Generating empty dashboard data.")

    customers = []
    all_agents = []
    total_mrr = 0
    tier_counts: dict[str, int] = {"hermes": 0, "openclaw": 0}

    for slug in slugs:
        try:
            cfg = load_customer(slug)
        except Exception as e:
            print(f"Warning: failed to load '{slug}': {e}")
            continue

        # Count agents per tier for this customer
        agent_tiers: dict[str, int] = {"hermes": 0, "openclaw": 0}
        for agent in cfg.agents:
            agent_tiers[agent.runtime] += 1
            tier_counts[agent.runtime] += 1

        # Calculate customer MRR
        customer_mrr = sum(
            count * stacks.get(tier, 0) for tier, count in agent_tiers.items()
        )
        total_mrr += customer_mrr

        # Determine status based on contract start date
        try:
            start = datetime.strptime(cfg.contract.start_date, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            now = datetime.now(timezone.utc)
            if start > now:
                status = "Onboarding"
            else:
                status = "Live"
        except (ValueError, TypeError):
            status = "Unknown"

        # Build tier summary string (e.g., "Hermes x3, OpenClaw x2")
        tier_parts = []
        for tier_name in ("hermes", "openclaw"):
            count = agent_tiers[tier_name]
            if count > 0:
                display = "Hermes" if tier_name == "hermes" else "OpenClaw"
                tier_parts.append(f"{display} ×{count}")
        tier_summary = ", ".join(tier_parts)

        customers.append(
            {
                "slug": cfg.customer.slug,
                "name": cfg.customer.legal_name,
                "vertical": cfg.customer.vertical.capitalize(),
                "tier": cfg.contract.tier,
                "tier_summary": tier_summary,
                "agent_count": len(cfg.agents),
                "status": status,
                "start_date": cfg.contract.start_date,
                "contact_name": cfg.customer.primary_contact.name,
                "mrr": customer_mrr,
                "health_digest": cfg.observability.health_digest_cadence,
                "watchdog_interval": cfg.observability.watchdog_interval_seconds,
            }
        )

        # Build agent entries
        for agent in cfg.agents:
            all_agents.append(
                {
                    "name": agent.name,
                    "role": agent.role,
                    "customer_slug": cfg.customer.slug,
                    "customer_name": cfg.customer.legal_name,
                    "runtime": agent.runtime,
                    "mcps": list(agent.mcps),
                    "connectors": list(agent.connectors),
                    "composio_apps": list(agent.composio_apps),
                    "second_brain": agent.second_brain.enabled,
                }
            )

    # Sort customers by MRR descending
    customers.sort(key=lambda c: c["mrr"], reverse=True)

    # Compute fleet stats
    total_agents = tier_counts["hermes"] + tier_counts["openclaw"]
    hermes_pct = (
        round(tier_counts["hermes"] / total_agents * 100) if total_agents else 0
    )
    openclaw_pct = 100 - hermes_pct if total_agents else 0
    avg_arpa = round(total_mrr / total_agents) if total_agents else 0

    # Infrastructure cost estimates (rough model)
    hermes_compute = tier_counts["hermes"] * 900  # ~$900/agent/mo
    openclaw_compute = tier_counts["openclaw"] * 600  # ~$600/agent/mo
    llm_cost = total_agents * 190  # ~$190/agent/mo avg
    mcp_connector_cost = max(500, total_agents * 90)  # baseline + per-agent
    total_infra = hermes_compute + openclaw_compute + llm_cost + mcp_connector_cost
    gross_margin = round((1 - total_infra / total_mrr) * 100, 1) if total_mrr else 0

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kpis": {
            "customer_count": len(customers),
            "agent_count": total_agents,
            "mrr": total_mrr,
            "arr": total_mrr * 12,
        },
        "tier_mix": {
            "hermes": {"count": tier_counts["hermes"], "pct": hermes_pct},
            "openclaw": {"count": tier_counts["openclaw"], "pct": openclaw_pct},
        },
        "pricing": stacks,
        "avg_arpa": avg_arpa,
        "costs": {
            "hermes_compute": hermes_compute,
            "openclaw_compute": openclaw_compute,
            "llm_api": llm_cost,
            "mcp_connectors": mcp_connector_cost,
            "total": total_infra,
            "gross_margin_pct": gross_margin,
        },
        "customers": customers,
        "agents": all_agents,
    }


def main() -> None:
    data = generate()
    out_path = REPO_ROOT / "dashboard-data.json"
    with out_path.open("w") as f:
        json.dump(data, f, indent=2)
    print(f"Dashboard data written to {out_path}")
    print(
        f"  {data['kpis']['customer_count']} customers, "
        f"{data['kpis']['agent_count']} agents, "
        f"${data['kpis']['mrr']:,}/mo MRR"
    )


if __name__ == "__main__":
    main()
