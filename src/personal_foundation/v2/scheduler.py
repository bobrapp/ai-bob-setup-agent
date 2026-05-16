"""APScheduler integration — emits schedule.* events on cron triggers.

Wires cron schedules defined in agent YAML files to the event bus.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.personal_foundation.v2.state import StateStore

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
AGENTS_DIR = REPO_ROOT / "agents"


class Scheduler:
    """Loads cron schedules from agent YAMLs and emits events on trigger."""

    def __init__(self, store: StateStore) -> None:
        self.store = store
        self._scheduler = AsyncIOScheduler()
        self._jobs: list[str] = []

    def load_schedules(self, agents_dir: Path | None = None) -> int:
        """Load cron schedules from all agent YAML files. Returns count."""
        directory = agents_dir or AGENTS_DIR
        if not directory.exists():
            return 0

        count = 0
        for yaml_file in sorted(directory.glob("*.yaml")):
            try:
                with yaml_file.open() as f:
                    data = yaml.safe_load(f)
                schedule = data.get("schedule")
                if not schedule:
                    continue

                agent_name = data.get("agent", {}).get("name", yaml_file.stem)
                cron_expr = schedule.get("cron", "")
                timezone = schedule.get("timezone", "America/Los_Angeles")

                if not cron_expr:
                    continue

                # Parse cron: "0 7 * * 1-5" → minute=0, hour=7, day_of_week=mon-fri
                parts = cron_expr.split()
                if len(parts) != 5:
                    log.warning("Scheduler: invalid cron '%s' in %s", cron_expr, yaml_file.name)
                    continue

                trigger = CronTrigger(
                    minute=parts[0],
                    hour=parts[1],
                    day=parts[2],
                    month=parts[3],
                    day_of_week=parts[4],
                    timezone=timezone,
                )

                # Determine event type from trigger pattern in agent def
                event_type = data.get("agent", {}).get("trigger", f"schedule.{agent_name}")

                self._scheduler.add_job(
                    self._emit_scheduled_event,
                    trigger=trigger,
                    args=[event_type, agent_name],
                    id=f"schedule_{agent_name}",
                    replace_existing=True,
                )
                self._jobs.append(agent_name)
                count += 1
                log.info("Scheduler: %s → '%s' (%s)", agent_name, cron_expr, timezone)

            except Exception as exc:
                log.error("Scheduler: failed to load %s: %s", yaml_file, exc)

        log.info("Scheduler: %d cron jobs loaded", count)
        return count

    def _emit_scheduled_event(self, event_type: str, agent_name: str) -> None:
        """Emit a scheduled event into the state store."""
        from datetime import datetime, timezone as tz
        self.store.emit_event(event_type, {
            "triggered_by": "scheduler",
            "agent": agent_name,
            "timestamp": datetime.now(tz.utc).isoformat(),
        })
        log.info("Scheduler: emitted %s for %s", event_type, agent_name)

    def start(self) -> None:
        """Start the scheduler."""
        self._scheduler.start()
        log.info("Scheduler: started (%d jobs)", len(self._jobs))

    def stop(self) -> None:
        """Stop the scheduler."""
        self._scheduler.shutdown(wait=False)
        log.info("Scheduler: stopped")

    @property
    def jobs(self) -> list[str]:
        return list(self._jobs)
