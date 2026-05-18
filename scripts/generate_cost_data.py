#!/usr/bin/env python3
"""Generate costs-data.json from the email poll cost log.

Reads:
  data/email_poll_costs.json — cost log from the email poller

Writes:
  costs-data.json — consumed by costs.html dashboard

Usage:
    python scripts/generate_cost_data.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
COST_LOG_FILE = DATA_DIR / "email_poll_costs.json"
OUTPUT_FILE = REPO_ROOT / "costs-data.json"


def generate() -> dict:
    """Build cost data structure from the poll log."""
    polls = []
    if COST_LOG_FILE.exists():
        try:
            polls = json.loads(COST_LOG_FILE.read_text())
        except (json.JSONDecodeError, ValueError):
            polls = []

    now = datetime.now(timezone.utc)
    day_ago = (now - timedelta(hours=24)).isoformat()
    week_ago = (now - timedelta(days=7)).isoformat()

    # All-time stats
    total_cost = sum(p.get("cost_usd", 0) for p in polls)
    total_classified = sum(p.get("classified", 0) for p in polls)
    total_action = sum(p.get("action_required", 0) for p in polls)
    total_archived = sum(p.get("archived", 0) for p in polls)
    total_errors = sum(p.get("errors", 0) for p in polls)

    # Last 24h
    recent_24h = [p for p in polls if p.get("timestamp", "") > day_ago]
    cost_24h = sum(p.get("cost_usd", 0) for p in recent_24h)
    classified_24h = sum(p.get("classified", 0) for p in recent_24h)

    # Last 7 days
    recent_7d = [p for p in polls if p.get("timestamp", "") > week_ago]
    cost_7d = sum(p.get("cost_usd", 0) for p in recent_7d)
    classified_7d = sum(p.get("classified", 0) for p in recent_7d)

    # Projected monthly (based on last 7 days if available, else all-time)
    if recent_7d:
        days_of_data = 7
        projected_monthly = (cost_7d / days_of_data) * 30
    elif polls:
        # Estimate from all data
        if len(polls) > 1:
            first_ts = polls[0].get("timestamp", "")
            last_ts = polls[-1].get("timestamp", "")
            try:
                first_dt = datetime.fromisoformat(first_ts)
                last_dt = datetime.fromisoformat(last_ts)
                days_span = max((last_dt - first_dt).total_seconds() / 86400, 1)
                projected_monthly = (total_cost / days_span) * 30
            except (ValueError, TypeError):
                projected_monthly = total_cost * 30
        else:
            projected_monthly = total_cost * 30
    else:
        projected_monthly = 0

    return {
        "generated_at": now.isoformat(),
        "summary": {
            "total_cost_usd": round(total_cost, 6),
            "total_classified": total_classified,
            "total_action_required": total_action,
            "total_archived": total_archived,
            "total_errors": total_errors,
            "total_poll_cycles": len(polls),
            "projected_monthly_usd": round(projected_monthly, 4),
        },
        "last_24h": {
            "cost_usd": round(cost_24h, 6),
            "classified": classified_24h,
            "poll_cycles": len(recent_24h),
        },
        "last_7d": {
            "cost_usd": round(cost_7d, 6),
            "classified": classified_7d,
            "poll_cycles": len(recent_7d),
        },
        "polls": polls[-50:],  # Last 50 entries for the chart
    }


def main() -> None:
    data = generate()
    OUTPUT_FILE.write_text(json.dumps(data, indent=2))
    print(f"Cost data written to {OUTPUT_FILE}")
    print(f"  Total cost: ${data['summary']['total_cost_usd']:.4f}")
    print(f"  Emails classified: {data['summary']['total_classified']}")
    print(f"  Projected monthly: ${data['summary']['projected_monthly_usd']:.2f}")


if __name__ == "__main__":
    main()
