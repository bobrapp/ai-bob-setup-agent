"""Hermes (and OpenClaw) runtime installer.

Installs and configures the agent runtime on a freshly-provisioned cloud
computer. Idempotent: re-running converges to the same configured state.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import structlog

from .config import AgentDef, StackConfig
from .mcp_config import MCPInstaller
from .orgo_client import CloudComputer, OrgoClient

log = structlog.get_logger(__name__)


@dataclass
class InstallResult:
    agent_name: str
    runtime: str
    cloud_computer_id: str
    public_endpoint: str | None
    mcps_installed: list[str]
    connectors_installed: list[str]
    second_brain_loaded: bool


class HermesInstaller:
    """Drives a fresh cloud computer to a configured agent runtime."""

    def __init__(self, orgo: OrgoClient, dry_run: bool = False) -> None:
        self.orgo = orgo
        self.dry_run = dry_run
        self.mcp = MCPInstaller(dry_run=dry_run)

    def install(
        self,
        cloud_computer: CloudComputer,
        agent: AgentDef,
        stack: StackConfig,
    ) -> InstallResult:
        log.info(
            "hermes.install.start",
            agent=agent.name,
            runtime=stack.stack,
            computer_id=cloud_computer.id,
        )

        # 1. Verify base image is correct
        expected_image = stack.runtime["base_image"]
        if cloud_computer.image != expected_image and not self.dry_run:
            log.warning(
                "hermes.install.image_mismatch",
                got=cloud_computer.image,
                expected=expected_image,
            )

        # 2. Bootstrap runtime
        license_key = self._runtime_license(stack.stack)
        self._run_remote(
            cloud_computer,
            "bootstrap_runtime",
            {
                "runtime": stack.stack,
                "version": stack.runtime.get("version", "latest"),
                "license_key": license_key,
            },
        )

        # 3. Install MCPs
        installed_mcps: list[str] = []
        for mcp_name in agent.mcps:
            normalized = "x_mcp" if mcp_name == "x" else mcp_name
            self.mcp.install(cloud_computer, normalized)
            installed_mcps.append(normalized)

        # 4. Install connectors
        installed_connectors: list[str] = []
        for connector in agent.connectors:
            self._run_remote(
                cloud_computer,
                "install_connector",
                {"connector": connector},
            )
            installed_connectors.append(connector)

        # 5. Load second-brain seed (if any)
        second_brain_loaded = False
        if agent.second_brain.enabled and agent.second_brain.seed_path:
            self._run_remote(
                cloud_computer,
                "load_second_brain",
                {"seed_path": agent.second_brain.seed_path, "layer": "obsidian"},
            )
            second_brain_loaded = True

        # 6. Apply model config
        self._run_remote(
            cloud_computer,
            "configure_model",
            {
                "primary": stack.models["primary"],
                "fallback": stack.models.get("fallback")
                or stack.models.get("light_fallback"),
                "light": stack.models.get("light"),
            },
        )

        # 7. Final reload
        self._run_remote(cloud_computer, "reload_runtime", {})

        log.info("hermes.install.done", agent=agent.name)
        return InstallResult(
            agent_name=agent.name,
            runtime=stack.stack,
            cloud_computer_id=cloud_computer.id,
            public_endpoint=cloud_computer.public_endpoint,
            mcps_installed=installed_mcps,
            connectors_installed=installed_connectors,
            second_brain_loaded=second_brain_loaded,
        )

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------
    def _runtime_license(self, runtime: str) -> str:
        env_var = (
            "HERMES_LICENSE_KEY" if runtime == "hermes" else "OPENCLAW_LICENSE_KEY"
        )
        return os.getenv(env_var, "")

    def _run_remote(
        self,
        cloud_computer: CloudComputer,
        action: str,
        payload: dict,
    ) -> dict:
        """Execute an action on the remote cloud computer.

        In production this dispatches over Orgo's exec API. Here it's a
        well-typed extension point — log the call and return a stub.
        """
        log.info(
            "hermes.remote",
            computer_id=cloud_computer.id,
            action=action,
            payload=payload,
        )
        if self.dry_run:
            return {"dry_run": True, "action": action}
        # Real implementation:
        # self.orgo._request(
        #     "POST",
        #     f"/computers/{cloud_computer.id}/exec",
        #     json={"action": action, "payload": payload},
        # )
        return {"ok": True, "action": action}
