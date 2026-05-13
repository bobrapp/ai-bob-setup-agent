"""Thin client for the Orgo cloud-computer platform.

This is the skeleton — real Orgo endpoints are documented at the URL Nick
shared in the source episode (https://startup-ideas-pod.link/orgo_ai). Drop
real paths in once you have an API key.

The interface mirrors the video's mental model:
- A `workspace` is a customer-scoped container.
- A `cloud_computer` is a per-agent VM that runs inside a workspace.
- An `image` is a base agent runtime (Hermes or OpenClaw).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

log = structlog.get_logger(__name__)


@dataclass
class Workspace:
    id: str
    customer_slug: str
    region: str


@dataclass
class CloudComputer:
    id: str
    workspace_id: str
    agent_name: str
    image: str
    status: str            # "provisioning" | "running" | "stopped" | "error"
    public_endpoint: str | None = None


class OrgoError(RuntimeError):
    """Raised when the Orgo API rejects a request."""


class OrgoClient:
    """HTTP client for Orgo. Re-runs are idempotent on (customer_slug, agent_name)."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        dry_run: bool = False,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key or os.getenv("ORGO_API_KEY", "")
        self.base_url = (base_url or os.getenv("ORGO_API_BASE", "https://api.orgo.ai/v1")).rstrip("/")
        self.dry_run = dry_run
        self.timeout = timeout
        if not self.api_key and not dry_run:
            raise OrgoError("ORGO_API_KEY missing. Set it in .env or run with dry_run=True.")

    # ---------------------------------------------------------------------
    # HTTP helpers
    # ---------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "ai-bob-setup-agent/0.1",
        }

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if self.dry_run:
            log.info("orgo.dry_run", method=method, url=url, kwargs=kwargs)
            return {"dry_run": True, "method": method, "url": url}
        with httpx.Client(timeout=self.timeout) as client:
            r = client.request(method, url, headers=self._headers(), **kwargs)
            if r.status_code >= 400:
                raise OrgoError(f"{method} {path} -> {r.status_code}: {r.text}")
            return r.json() if r.text else {}

    # ---------------------------------------------------------------------
    # Workspaces
    # ---------------------------------------------------------------------
    def get_workspace_by_slug(self, customer_slug: str) -> Workspace | None:
        """Return the existing workspace for a customer, or None."""
        log.debug("orgo.get_workspace", customer_slug=customer_slug)
        if self.dry_run:
            return None
        try:
            data = self._request("GET", f"/workspaces?slug={customer_slug}")
            items = data.get("items", [])
            if not items:
                return None
            w = items[0]
            return Workspace(id=w["id"], customer_slug=customer_slug, region=w.get("region", ""))
        except OrgoError as exc:
            log.warning("orgo.get_workspace.failed", error=str(exc))
            return None

    def ensure_workspace(self, customer_slug: str, region: str | None = None) -> Workspace:
        """Idempotent: create workspace if missing, otherwise return existing."""
        existing = self.get_workspace_by_slug(customer_slug)
        if existing:
            log.info("orgo.workspace.existing", id=existing.id, customer_slug=customer_slug)
            return existing
        region = region or os.getenv("ORGO_DEFAULT_REGION", "us-west-2")
        log.info("orgo.workspace.create", customer_slug=customer_slug, region=region)
        data = self._request(
            "POST",
            "/workspaces",
            json={"slug": customer_slug, "region": region},
        )
        if self.dry_run:
            return Workspace(id=f"ws_dry_{customer_slug}", customer_slug=customer_slug, region=region)
        return Workspace(id=data["id"], customer_slug=customer_slug, region=region)

    def delete_workspace(self, workspace_id: str) -> None:
        log.info("orgo.workspace.delete", id=workspace_id)
        self._request("DELETE", f"/workspaces/{workspace_id}")

    # ---------------------------------------------------------------------
    # Cloud computers (one per agent)
    # ---------------------------------------------------------------------
    def list_cloud_computers(self, workspace_id: str) -> list[CloudComputer]:
        log.debug("orgo.cloud_computers.list", workspace_id=workspace_id)
        if self.dry_run:
            return []
        data = self._request("GET", f"/workspaces/{workspace_id}/computers")
        return [
            CloudComputer(
                id=c["id"],
                workspace_id=workspace_id,
                agent_name=c.get("name", ""),
                image=c.get("image", ""),
                status=c.get("status", "unknown"),
                public_endpoint=c.get("public_endpoint"),
            )
            for c in data.get("items", [])
        ]

    def ensure_cloud_computer(
        self,
        workspace_id: str,
        agent_name: str,
        image: str,
        cpu_vcpus: int = 4,
        memory_gb: int = 8,
        disk_gb: int = 80,
    ) -> CloudComputer:
        """Idempotent: return existing cloud computer or create a new one."""
        for cc in self.list_cloud_computers(workspace_id):
            if cc.agent_name == agent_name:
                log.info("orgo.cloud_computer.existing", id=cc.id, agent_name=agent_name)
                return cc
        log.info("orgo.cloud_computer.create", agent_name=agent_name, image=image)
        data = self._request(
            "POST",
            f"/workspaces/{workspace_id}/computers",
            json={
                "name": agent_name,
                "image": image,
                "cpu_vcpus": cpu_vcpus,
                "memory_gb": memory_gb,
                "disk_gb": disk_gb,
            },
        )
        if self.dry_run:
            return CloudComputer(
                id=f"cc_dry_{agent_name}",
                workspace_id=workspace_id,
                agent_name=agent_name,
                image=image,
                status="provisioning",
            )
        return CloudComputer(
            id=data["id"],
            workspace_id=workspace_id,
            agent_name=agent_name,
            image=image,
            status=data.get("status", "provisioning"),
            public_endpoint=data.get("public_endpoint"),
        )

    def delete_cloud_computer(self, workspace_id: str, computer_id: str) -> None:
        log.info("orgo.cloud_computer.delete", workspace_id=workspace_id, computer_id=computer_id)
        self._request("DELETE", f"/workspaces/{workspace_id}/computers/{computer_id}")

    # ---------------------------------------------------------------------
    # Health
    # ---------------------------------------------------------------------
    def ping(self) -> bool:
        """Return True if the Orgo API responds."""
        try:
            self._request("GET", "/health")
            return True
        except OrgoError:
            return False
