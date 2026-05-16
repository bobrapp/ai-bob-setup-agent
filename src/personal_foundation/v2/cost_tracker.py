"""Cost tracker — monitors LLM token usage and estimates spend per agent.

Tracks input/output tokens per call, maps to model pricing, produces
weekly cost reports.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from src.personal_foundation.v2.state import StateStore

log = logging.getLogger(__name__)

# Pricing per 1M tokens (as of May 2026)
MODEL_PRICING = {
    "groq/llama-3.1-70b-versatile": {"input": 0.59, "output": 0.79},
    "groq/llama-3.1-8b-instant": {"input": 0.05, "output": 0.08},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
}


class CostTracker:
    """Tracks LLM costs per agent and produces reports."""

    def __init__(self, store: StateStore) -> None:
        self.store = store
        self._init_table()

    def _init_table(self) -> None:
        with self.store._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cost_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent TEXT NOT NULL,
                    model TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    cost_usd REAL NOT NULL DEFAULT 0.0,
                    cached INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cost_agent ON cost_log(agent)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cost_created ON cost_log(created_at)")

    def record(self, agent: str, model: str, input_tokens: int, output_tokens: int, cached: bool = False) -> float:
        """Record a single LLM call's token usage. Returns estimated cost in USD."""
        cost = self._estimate_cost(model, input_tokens, output_tokens)
        if cached:
            cost = 0.0  # Cached responses are free

        with self.store._conn() as conn:
            conn.execute(
                """INSERT INTO cost_log (agent, model, input_tokens, output_tokens, cost_usd, cached, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (agent, model, input_tokens, output_tokens, cost, int(cached),
                 datetime.now(timezone.utc).isoformat()),
            )
        return cost

    def get_daily_cost(self, date: str = "") -> dict:
        """Get cost breakdown for a specific date (default: today)."""
        if not date:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        with self.store._conn() as conn:
            rows = conn.execute(
                """SELECT agent, model, SUM(input_tokens) as total_input, 
                   SUM(output_tokens) as total_output, SUM(cost_usd) as total_cost,
                   COUNT(*) as calls, SUM(cached) as cached_calls
                   FROM cost_log WHERE created_at LIKE ? GROUP BY agent, model""",
                (f"{date}%",),
            ).fetchall()

        result = {"date": date, "total_cost": 0.0, "total_calls": 0, "by_agent": {}}
        for r in rows:
            agent = r["agent"]
            if agent not in result["by_agent"]:
                result["by_agent"][agent] = {"cost": 0.0, "calls": 0, "cached": 0}
            result["by_agent"][agent]["cost"] += r["total_cost"]
            result["by_agent"][agent]["calls"] += r["calls"]
            result["by_agent"][agent]["cached"] += r["cached_calls"]
            result["total_cost"] += r["total_cost"]
            result["total_calls"] += r["calls"]

        return result

    def get_weekly_report(self) -> dict:
        """Get cost report for the last 7 days."""
        now = datetime.now(timezone.utc)
        week_ago = (now - timedelta(days=7)).isoformat()

        with self.store._conn() as conn:
            # Total
            row = conn.execute(
                "SELECT SUM(cost_usd) as total, COUNT(*) as calls, SUM(cached) as cached FROM cost_log WHERE created_at > ?",
                (week_ago,),
            ).fetchone()

            # By model
            model_rows = conn.execute(
                """SELECT model, SUM(cost_usd) as cost, COUNT(*) as calls, 
                   SUM(input_tokens) as input_tok, SUM(output_tokens) as output_tok
                   FROM cost_log WHERE created_at > ? GROUP BY model ORDER BY cost DESC""",
                (week_ago,),
            ).fetchall()

            # By agent
            agent_rows = conn.execute(
                "SELECT agent, SUM(cost_usd) as cost, COUNT(*) as calls FROM cost_log WHERE created_at > ? GROUP BY agent ORDER BY cost DESC",
                (week_ago,),
            ).fetchall()

        return {
            "period": f"{(now - timedelta(days=7)).strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')}",
            "total_cost": round(row["total"] or 0, 4),
            "total_calls": row["calls"] or 0,
            "cached_calls": row["cached"] or 0,
            "cache_savings_pct": round((row["cached"] or 0) / max(row["calls"] or 1, 1) * 100, 1),
            "by_model": [{"model": r["model"], "cost": round(r["cost"], 4), "calls": r["calls"],
                         "tokens": r["input_tok"] + r["output_tok"]} for r in model_rows],
            "by_agent": [{"agent": r["agent"], "cost": round(r["cost"], 4), "calls": r["calls"]} for r in agent_rows],
        }

    def _estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost in USD based on model pricing."""
        pricing = MODEL_PRICING.get(model, {"input": 1.0, "output": 2.0})
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        return round(input_cost + output_cost, 6)
