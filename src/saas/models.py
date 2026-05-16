"""Multi-tenant data models — organizations, users, billing.

Uses PostgreSQL with row-level security for tenant isolation.
SQLite version available for development/testing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PlanTier(str, Enum):
    """Subscription plan tiers."""
    FREE = "free"           # 1 agent, 100 actions/month, no API
    STARTER = "starter"     # 3 agents, 1000 actions/month, $29/mo
    PRO = "pro"             # 10 agents, 10000 actions/month, $79/mo
    ENTERPRISE = "enterprise"  # Unlimited, custom pricing


class Organization(BaseModel):
    """A tenant organization."""
    id: str
    name: str
    slug: str                   # URL-safe identifier
    plan: PlanTier = PlanTier.FREE
    owner_email: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    is_active: bool = True
    settings: dict = Field(default_factory=dict)

    # Usage limits per plan
    @property
    def max_agents(self) -> int:
        return {"free": 1, "starter": 3, "pro": 10, "enterprise": 999}[self.plan.value]

    @property
    def max_actions_per_month(self) -> int:
        return {"free": 100, "starter": 1000, "pro": 10000, "enterprise": 999999}[self.plan.value]


class OrgUser(BaseModel):
    """A user within an organization."""
    id: str
    org_id: str
    email: str
    name: str
    role: str = "operator"      # owner, operator, viewer
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_login: Optional[datetime] = None


class UsageRecord(BaseModel):
    """Monthly usage tracking per organization."""
    org_id: str
    month: str                  # "2026-05"
    actions_count: int = 0
    llm_calls: int = 0
    llm_cost_usd: float = 0.0
    agents_active: int = 0
    approvals_processed: int = 0


class BillingEvent(BaseModel):
    """Billing event for audit trail."""
    id: str
    org_id: str
    event_type: str             # subscription_created, payment_succeeded, payment_failed
    amount_usd: float = 0.0
    stripe_event_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = Field(default_factory=dict)
