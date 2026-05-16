"""Configuration loading and validation for the personal + foundation automation system.

INTERNAL USE ONLY — not part of the ai-bob-setup-agent customer product.

Config lives in config/personal-foundation/config.yaml (gitignored).
See config/personal-foundation/config.example.yaml for the full schema.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PERSONAL_FOUNDATION_CONFIG_DIR = REPO_ROOT / "config" / "personal-foundation"
DEFAULT_CONFIG_PATH = PERSONAL_FOUNDATION_CONFIG_DIR / "config.yaml"


# ---------------------------------------------------------------------------
# Sub-configs
# ---------------------------------------------------------------------------


class TelegramFoundationConfig(BaseModel):
    """Telegram bot credentials and chat IDs for the approval channel."""

    bot_token: str
    approval_chat_id: str  # Bob + Ken's shared approval channel
    bob_chat_id: str
    ken_chat_id: str


class CircleConfig(BaseModel):
    """Circle.so Admin API credentials."""

    api_key: str
    community_id: str
    welcome_space_id: str
    digest_space_id: str
    headless_auth_jwt: str  # for DM delivery via Headless Auth


class ComposioConfig(BaseModel):
    """Composio credentials for Asana and Trello integration."""

    api_key: str
    asana_workspace_id: str
    trello_board_id: str


class PerplexityConfig(BaseModel):
    """Perplexity MCP credentials for live research search."""

    api_key: str


# ---------------------------------------------------------------------------
# Root config
# ---------------------------------------------------------------------------


class FoundationConfig(BaseModel):
    """Root configuration for the personal + foundation automation system."""

    telegram: TelegramFoundationConfig
    circle: CircleConfig
    composio: ComposioConfig
    perplexity: PerplexityConfig

    # Operational knobs
    dry_run: bool = False
    bob_timezone: str = "America/Los_Angeles"
    max_emails_per_hour: int = 50
    approval_expiry_hours: int = 24
    agent_failure_rate_threshold: float = Field(default=0.10, ge=0.0, le=1.0)
    agent_consecutive_failure_threshold: int = Field(default=5, ge=1)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_config(path: str | Path | None = None) -> FoundationConfig:
    """Load and validate the foundation config from YAML.

    Args:
        path: Path to config.yaml. Defaults to
              config/personal-foundation/config.yaml relative to repo root.

    Returns:
        Validated FoundationConfig instance.

    Raises:
        FileNotFoundError: If the config file does not exist.
        pydantic.ValidationError: If the config is invalid.
    """
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(
            f"Foundation config not found at {config_path}. "
            f"Copy config/personal-foundation/config.example.yaml to "
            f"config/personal-foundation/config.yaml and fill in your credentials."
        )
    with config_path.open("r") as f:
        data = yaml.safe_load(f)
    return FoundationConfig(**data)
