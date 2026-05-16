"""Plugin interface for custom integrations.

Create a plugin by subclassing IntegrationPlugin:

    from aigovops_framework.plugins import IntegrationPlugin

    class SlackPlugin(IntegrationPlugin):
        name = "slack"

        async def execute(self, method: str, params: dict) -> dict:
            if method == "send_message":
                # Your Slack API call here
                return {"ok": True}
            return {"error": "unknown method"}

Register with the framework:
    fw.register_plugin(SlackPlugin())
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class IntegrationPlugin(ABC):
    """Base class for integration plugins.

    Subclass this to add new integrations (Slack, Discord, Notion, etc.)
    """

    name: str = "unnamed"
    description: str = ""
    version: str = "0.1.0"

    @abstractmethod
    async def execute(self, method: str, params: dict) -> dict:
        """Execute an integration method.

        Args:
            method: The method to call (e.g., "send_message", "create_task")
            params: Parameters for the method

        Returns:
            Result dict with at least {"ok": bool}
        """
        ...

    async def health_check(self) -> bool:
        """Check if the integration is healthy/reachable. Override if needed."""
        return True

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name} v{self.version}>"
