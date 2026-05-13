#!/usr/bin/env python3
"""Long-running watchdog. Polls every customer's agents and alerts on failure.

Run via `make watchdog` or as a systemd unit.
Ctrl-C to stop.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import structlog  # noqa: E402

from src.config import list_customers, load_customer, load_env  # noqa: E402
from src.observability import Watchdog  # noqa: E402
from src.orgo_client import OrgoClient  # noqa: E402
from src.telegram_meta import TelegramMeta  # noqa: E402

log = structlog.get_logger(__name__)


def main() -> int:
    load_env()
    slugs = list_customers()
    if not slugs:
        log.warning("watchdog.no_customers")
        return 0

    customers = [load_customer(s) for s in slugs]
    orgo = OrgoClient(dry_run=False)
    telegram = TelegramMeta()
    wd = Watchdog(orgo, telegram=telegram)

    try:
        asyncio.run(wd.run_forever(customers))
    except KeyboardInterrupt:
        log.info("watchdog.stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
