"""v2 Main entry point — starts all components.

Usage:
    python -m src.personal_foundation.v2              # Start everything
    python -m src.personal_foundation.v2 --dry-run    # No external calls
    python -m src.personal_foundation.v2 --api-only   # Just the API server
    python -m src.personal_foundation.v2 --test       # Send test notification to all channels
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("aigovops.v2")


async def start_system(dry_run: bool = False, api_only: bool = False) -> None:
    """Start the full v2 system."""
    from src.personal_foundation.v2.state import StateStore
    from src.personal_foundation.v2.event_bus import EventBus
    from src.personal_foundation.v2.policy import PolicyEngine
    from src.personal_foundation.v2.engine import AgentEngine
    from src.personal_foundation.v2.channels.dispatcher import NotificationDispatcher
    from src.personal_foundation.v2.channels.telegram import TelegramChannel
    from src.personal_foundation.v2.channels.whatsapp import WhatsAppChannel
    from src.personal_foundation.v2.channels.sms import SMSChannel
    from src.personal_foundation.v2.channels.web import WebChannel
    from src.personal_foundation.v2.channels.voice import VoiceChannel
    from src.personal_foundation.v2 import api as api_module

    # Initialize core
    store = StateStore()
    event_bus = EventBus(store, poll_interval=1.0)
    policy_engine = PolicyEngine()

    # Initialize channels
    dispatcher = NotificationDispatcher(store)

    # Telegram (if configured)
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if tg_token:
        tg_channel = TelegramChannel(
            bot_token=tg_token,
            chat_ids={
                "bob": os.getenv("TELEGRAM_BOB_CHAT_ID", ""),
                "ken": os.getenv("TELEGRAM_KEN_CHAT_ID", ""),
                "approval": os.getenv("TELEGRAM_APPROVAL_CHAT_ID", ""),
            },
            store=store,
        )
        dispatcher.register_channel(tg_channel)

    # WhatsApp (if configured)
    if os.getenv("WHATSAPP_TOKEN") or os.getenv("TWILIO_ACCOUNT_SID"):
        wa_channel = WhatsAppChannel(
            phone_numbers={
                "bob": os.getenv("BOB_PHONE", ""),
                "ken": os.getenv("KEN_PHONE", ""),
            },
            provider="meta" if os.getenv("WHATSAPP_TOKEN") else "twilio",
        )
        dispatcher.register_channel(wa_channel)

    # SMS (if configured)
    if os.getenv("TWILIO_ACCOUNT_SID") and os.getenv("TWILIO_SMS_FROM"):
        sms_channel = SMSChannel(
            phone_numbers={
                "bob": os.getenv("BOB_PHONE", ""),
                "ken": os.getenv("KEN_PHONE", ""),
            },
        )
        dispatcher.register_channel(sms_channel)

    # Web (always available)
    web_channel = WebChannel(broadcast_fn=api_module.broadcast)
    dispatcher.register_channel(web_channel)

    # Voice (always available — responds via API)
    voice_channel = VoiceChannel()
    dispatcher.register_channel(voice_channel)

    # Set API store reference
    api_module._store = store

    # Initialize agent engine
    agent_engine = AgentEngine(
        store=store, event_bus=event_bus,
        policy_engine=policy_engine, dry_run=dry_run,
    )
    agents_loaded = agent_engine.load_agents()

    # Subscribe dispatcher to notification events
    async def handle_notification(event: dict):
        payload = event.get("payload", {})
        await dispatcher.notify(
            recipient=payload.get("recipient", "bob"),
            text=payload.get("message", ""),
            urgency=payload.get("urgency", "normal"),
        )

    async def handle_approval_created(event: dict):
        payload = event.get("payload", {})
        items = store.get_pending_approvals()
        if items:
            await dispatcher.send_approval_request(items[-1])

    event_bus.subscribe("notification.*", "dispatcher", handle_notification)
    event_bus.subscribe("approval.created", "dispatcher", handle_approval_created)

    # Log startup
    store.log_audit(
        agent="system/main", action="startup",
        result_summary=f"v2 started: {agents_loaded} agents, dry_run={dry_run}",
        dry_run=dry_run,
    )

    log.info("=" * 60)
    log.info("AIGovOps Foundation Automation v2")
    log.info("=" * 60)
    log.info("  Agents loaded: %d", agents_loaded)
    log.info("  Channels: %s", ", ".join(dispatcher._channels.keys()))
    log.info("  Dry-run: %s", dry_run)
    log.info("  API: http://localhost:8000")
    log.info("  Docs: http://localhost:8000/docs")
    log.info("=" * 60)

    if api_only:
        # Just run the API server
        config = uvicorn.Config(api_module.app, host="0.0.0.0", port=8000, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()
    else:
        # Run everything concurrently
        await dispatcher.start_all()

        tasks = [
            asyncio.create_task(event_bus.start()),
            asyncio.create_task(
                uvicorn.Server(
                    uvicorn.Config(api_module.app, host="0.0.0.0", port=8000, log_level="info")
                ).serve()
            ),
        ]

        try:
            await asyncio.gather(*tasks)
        except (KeyboardInterrupt, asyncio.CancelledError):
            log.info("Shutting down...")
            event_bus.stop()
            await dispatcher.stop_all()
            store.log_audit(agent="system/main", action="shutdown", result_summary="Clean shutdown")


async def send_test(dry_run: bool = False) -> None:
    """Send a test notification to all configured channels."""
    from src.personal_foundation.v2.state import StateStore
    from src.personal_foundation.v2.channels.dispatcher import NotificationDispatcher
    from src.personal_foundation.v2.channels.telegram import TelegramChannel
    from src.personal_foundation.v2.channels.web import WebChannel

    store = StateStore()
    dispatcher = NotificationDispatcher(store)

    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if tg_token:
        tg = TelegramChannel(
            bot_token=tg_token,
            chat_ids={
                "bob": os.getenv("TELEGRAM_BOB_CHAT_ID", ""),
                "ken": os.getenv("TELEGRAM_KEN_CHAT_ID", ""),
                "approval": os.getenv("TELEGRAM_APPROVAL_CHAT_ID", ""),
            },
            store=store,
        )
        dispatcher.register_channel(tg)
        await tg.start()

    web = WebChannel()
    dispatcher.register_channel(web)

    # Send test
    item_id = store.enqueue_approval(
        agent="system/test",
        action_type="test",
        description="Test notification — if you see this, all channels are working!",
        draft_content="This is a test. Tap Approve to confirm the system works.",
    )

    results = await dispatcher.send_approval_request(store.get_pending_approvals()[-1])
    log.info("Test results: %s", results)

    # Also send a plain notification
    await dispatcher.notify("bob", "🧪 AIGovOps v2 test notification. System is operational.", "high")

    log.info("✅ Test complete. Check your channels.")

    if tg_token:
        await tg.stop()


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    api_only = "--api-only" in sys.argv
    test_mode = "--test" in sys.argv

    if test_mode:
        asyncio.run(send_test(dry_run))
    else:
        asyncio.run(start_system(dry_run=dry_run, api_only=api_only))


if __name__ == "__main__":
    main()
