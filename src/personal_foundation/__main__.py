"""Entry point for the personal + foundation automation system.

Usage:
    python -m src.personal_foundation          # Start the bot + orchestrator
    python -m src.personal_foundation --dry-run # Start in dry-run mode
    python -m src.personal_foundation --test    # Send a test approval item

INTERNAL USE ONLY.
"""

from __future__ import annotations

import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("personal_foundation")


def main() -> None:
    from src.personal_foundation.config import load_config
    from src.personal_foundation.approval_queue import ApprovalItem, ApprovalQueue
    from src.personal_foundation.telegram_bot import FoundationTelegramBot
    from src.personal_foundation.audit_shim import log_action

    # Parse args
    dry_run = "--dry-run" in sys.argv
    test_mode = "--test" in sys.argv

    # Load config
    try:
        config = load_config()
    except FileNotFoundError as exc:
        log.error(str(exc))
        sys.exit(1)

    if dry_run:
        config.dry_run = True
        log.info("🔒 Running in DRY-RUN mode — no external API calls will be made")

    # Initialize
    queue = ApprovalQueue()
    bot = FoundationTelegramBot(config=config, approval_queue=queue)

    log_action(
        action="foundation/orchestrator:startup",
        command="python -m src.personal_foundation" + (" --dry-run" if dry_run else ""),
        status="success",
        result_summary=f"System started (dry_run={config.dry_run})",
    )

    if test_mode:
        # Send a test approval item
        test_item = ApprovalItem(
            agent="foundation/orchestrator",
            action_type="test",
            description="This is a test approval item. Tap Approve to confirm the bot works.",
            draft_content="If you can see this and tap Approve, the system is working correctly!",
            rationale="Sent via --test flag to verify Telegram integration.",
        )
        queue.enqueue(test_item)

        async def _send_test():
            app = bot.build()
            await app.initialize()
            await app.start()
            await bot.present_item(test_item)
            log.info("✅ Test item sent to Telegram. Check your approval channel.")
            await asyncio.sleep(2)
            await app.stop()
            await app.shutdown()

        asyncio.run(_send_test())
        return

    # Run the bot
    log.info("🚀 Starting Foundation Automation Bot...")
    log.info("   Approval channel: %s", config.telegram.approval_chat_id)
    log.info("   Dry-run: %s", config.dry_run)
    log.info("   Press Ctrl+C to stop")

    asyncio.run(bot.run())


if __name__ == "__main__":
    main()
