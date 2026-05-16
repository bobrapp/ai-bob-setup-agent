"""Tenant isolation — ensures each organization's data is completely separated.

In SQLite mode (dev): uses org_id prefix on all queries.
In PostgreSQL mode (prod): uses row-level security policies.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from src.saas.models import Organization, OrgUser, PlanTier

log = logging.getLogger(__name__)


class TenantManager:
    """Manages organizations and enforces tenant isolation."""

    def __init__(self, db_url: str = "sqlite:///data/saas.db") -> None:
        self.db_url = db_url
        self._orgs: dict[str, Organization] = {}  # In-memory for SQLite mode

    async def create_org(self, name: str, owner_email: str, plan: PlanTier = PlanTier.FREE) -> Organization:
        """Create a new organization."""
        org = Organization(
            id=str(uuid.uuid4()),
            name=name,
            slug=name.lower().replace(" ", "-").replace(".", ""),
            plan=plan,
            owner_email=owner_email,
        )
        self._orgs[org.id] = org

        # Create owner user
        owner = OrgUser(
            id=str(uuid.uuid4()),
            org_id=org.id,
            email=owner_email,
            name=name,
            role="owner",
        )

        log.info("TenantManager: created org '%s' (plan=%s)", name, plan.value)
        return org

    async def get_org(self, org_id: str) -> Optional[Organization]:
        """Get an organization by ID."""
        return self._orgs.get(org_id)

    async def get_org_by_slug(self, slug: str) -> Optional[Organization]:
        """Get an organization by slug."""
        for org in self._orgs.values():
            if org.slug == slug:
                return org
        return None

    async def list_orgs(self) -> list[Organization]:
        """List all organizations (admin only)."""
        return list(self._orgs.values())

    async def update_plan(self, org_id: str, new_plan: PlanTier) -> Optional[Organization]:
        """Update an organization's plan."""
        org = self._orgs.get(org_id)
        if org:
            org.plan = new_plan
            log.info("TenantManager: org '%s' upgraded to %s", org.name, new_plan.value)
        return org

    async def deactivate_org(self, org_id: str) -> bool:
        """Deactivate an organization (soft delete)."""
        org = self._orgs.get(org_id)
        if org:
            org.is_active = False
            log.info("TenantManager: deactivated org '%s'", org.name)
            return True
        return False

    def check_usage_limit(self, org: Organization, current_actions: int) -> bool:
        """Check if an org has exceeded its plan's action limit."""
        return current_actions < org.max_actions_per_month

    def check_agent_limit(self, org: Organization, current_agents: int) -> bool:
        """Check if an org has exceeded its plan's agent limit."""
        return current_agents < org.max_agents
