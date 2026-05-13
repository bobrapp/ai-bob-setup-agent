"""MCP (Model Context Protocol) installer.

Wires Perplexity, Context7, and X MCPs into a cloud-computer-resident agent
so the agent has live web search, live docs, and live social signals.
"""

from __future__ import annotations

import os

import structlog

from .orgo_client import CloudComputer

log = structlog.get_logger(__name__)


MCP_REGISTRY: dict[str, dict] = {
    "perplexity": {
        "purpose": "live_web_search",
        "env_var": "PERPLEXITY_API_KEY",
        "package": "@modelcontextprotocol/server-perplexity",
    },
    "context7": {
        "purpose": "live_docs",
        "env_var": "CONTEXT7_API_KEY",
        "package": "@upstash/context7-mcp",
    },
    "x_mcp": {
        "purpose": "live_social_signals",
        "env_var": "X_MCP_BEARER_TOKEN",
        "package": "x-mcp-server",
    },
    "orgo": {
        "purpose": "agent_cloud_control",
        "env_var": "ORGO_API_KEY",
        "package": "@nickvasilescu/orgo-mcp",
        "repo": "https://github.com/nickvasilescu/orgo-mcp",
        "note": "Lets agents manage their own cloud computers via Orgo API",
    },
}


class MCPInstaller:
    """Installs MCPs onto a cloud computer."""

    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run

    def install(self, cloud_computer: CloudComputer, mcp_name: str) -> None:
        if mcp_name not in MCP_REGISTRY:
            log.warning("mcp.unknown", mcp_name=mcp_name)
            return
        spec = MCP_REGISTRY[mcp_name]
        api_key = os.getenv(spec["env_var"], "")
        if not api_key and not self.dry_run:
            log.warning("mcp.missing_key", mcp_name=mcp_name, env_var=spec["env_var"])
        log.info(
            "mcp.install",
            computer_id=cloud_computer.id,
            mcp_name=mcp_name,
            package=spec["package"],
            has_key=bool(api_key),
        )
        if self.dry_run:
            return
        # Real implementation: orgo exec to install the MCP package on the cloud computer.
        # Example sketch:
        #   orgo.exec(cloud_computer.id, f"npm install -g {spec['package']}")
        #   orgo.exec(cloud_computer.id, "echo 'config' > ~/.mcp/<name>.json")
