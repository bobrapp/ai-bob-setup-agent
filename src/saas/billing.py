"""Stripe billing integration for the SaaS layer.

Handles:
- Subscription creation (checkout sessions)
- Webhook processing (payment events)
- Usage metering
- Plan upgrades/downgrades
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

STRIPE_API_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# Price IDs (set these in Stripe Dashboard)
PRICE_IDS = {
    "starter": os.getenv("STRIPE_PRICE_STARTER", "price_starter"),
    "pro": os.getenv("STRIPE_PRICE_PRO", "price_pro"),
    "enterprise": os.getenv("STRIPE_PRICE_ENTERPRISE", "price_enterprise"),
}


class BillingService:
    """Manages Stripe subscriptions and billing."""

    def __init__(self) -> None:
        self._stripe = None
        if STRIPE_API_KEY:
            try:
                import stripe
                stripe.api_key = STRIPE_API_KEY
                self._stripe = stripe
            except ImportError:
                log.warning("BillingService: stripe package not installed")

    @property
    def is_configured(self) -> bool:
        return self._stripe is not None and bool(STRIPE_API_KEY)

    async def create_checkout_session(
        self, org_id: str, plan: str, success_url: str, cancel_url: str
    ) -> Optional[str]:
        """Create a Stripe Checkout session. Returns the session URL."""
        if not self.is_configured:
            log.warning("BillingService: Stripe not configured")
            return None

        price_id = PRICE_IDS.get(plan)
        if not price_id:
            return None

        try:
            session = self._stripe.checkout.Session.create(
                mode="subscription",
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={"org_id": org_id, "plan": plan},
            )
            return session.url
        except Exception as exc:
            log.error("BillingService: checkout failed: %s", exc)
            return None

    async def handle_webhook(self, payload: bytes, signature: str) -> dict:
        """Process a Stripe webhook event. Returns event data."""
        if not self.is_configured:
            return {"error": "not_configured"}

        try:
            event = self._stripe.Webhook.construct_event(
                payload, signature, STRIPE_WEBHOOK_SECRET
            )

            event_type = event["type"]
            data = event["data"]["object"]

            if event_type == "checkout.session.completed":
                return {
                    "action": "subscription_created",
                    "org_id": data.get("metadata", {}).get("org_id"),
                    "customer_id": data.get("customer"),
                    "subscription_id": data.get("subscription"),
                }
            elif event_type == "invoice.payment_succeeded":
                return {
                    "action": "payment_succeeded",
                    "customer_id": data.get("customer"),
                    "amount": data.get("amount_paid", 0) / 100,
                }
            elif event_type == "invoice.payment_failed":
                return {
                    "action": "payment_failed",
                    "customer_id": data.get("customer"),
                }
            elif event_type == "customer.subscription.deleted":
                return {
                    "action": "subscription_cancelled",
                    "customer_id": data.get("customer"),
                }

            return {"action": "unhandled", "type": event_type}

        except Exception as exc:
            log.error("BillingService: webhook error: %s", exc)
            return {"error": str(exc)}

    async def get_usage(self, org_id: str) -> dict:
        """Get current month's usage for an organization."""
        # In production, query the usage_records table
        return {
            "org_id": org_id,
            "month": datetime.now(timezone.utc).strftime("%Y-%m"),
            "actions": 0,
            "llm_calls": 0,
            "cost_usd": 0.0,
        }

    async def cancel_subscription(self, subscription_id: str) -> bool:
        """Cancel a subscription at period end."""
        if not self.is_configured:
            return False
        try:
            self._stripe.Subscription.modify(
                subscription_id, cancel_at_period_end=True
            )
            return True
        except Exception as exc:
            log.error("BillingService: cancel failed: %s", exc)
            return False
