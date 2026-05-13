"""Configuration loading and validation.

Customer configs live in config/customers/<slug>.yaml.
Stack definitions live in config/stacks/{hermes,openclaw}.yaml.
Operator credentials come from .env.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"
STACKS_DIR = CONFIG_DIR / "stacks"
CUSTOMERS_DIR = CONFIG_DIR / "customers"


# ---------------------------------------------------------------------------
# .env loading
# ---------------------------------------------------------------------------
def load_env(env_path: Path | None = None) -> None:
    """Load environment variables from .env. Safe to call multiple times."""
    target = env_path or (REPO_ROOT / ".env")
    if target.exists():
        load_dotenv(target, override=False)


# ---------------------------------------------------------------------------
# Operator environment
# ---------------------------------------------------------------------------
REQUIRED_ENV_KEYS = (
    "ORGO_API_KEY",
    "OPENAI_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CONTROL_CHAT_ID",
)

OPTIONAL_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "ZAI_API_KEY",
    "KIMI_API_KEY",
    "PERPLEXITY_API_KEY",
    "CONTEXT7_API_KEY",
    "X_MCP_BEARER_TOKEN",
    "COMPOSIO_API_KEY",
    "AGENT_MAIL_API_KEY",
    "AGENT_MAIL_DOMAIN",
    "HERMES_LICENSE_KEY",
    "OPENCLAW_LICENSE_KEY",
    "ALERT_EMAIL_FROM",
    "ALERT_EMAIL_TO",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
)


def check_env() -> dict[str, list[str]]:
    """Return missing required and optional env keys."""
    load_env()
    missing_required = [k for k in REQUIRED_ENV_KEYS if not os.getenv(k)]
    missing_optional = [k for k in OPTIONAL_ENV_KEYS if not os.getenv(k)]
    return {"required": missing_required, "optional": missing_optional}


# ---------------------------------------------------------------------------
# Customer config schema
# ---------------------------------------------------------------------------
Vertical = Literal[
    "marketing", "law", "insurance", "manufacturing", "wholesale", "real_estate"
]
Tier = Literal["hermes", "openclaw"]
MCPName = Literal["perplexity", "context7", "x", "x_mcp", "orgo"]
ConnectorName = Literal["composio", "agent_mail"]
ComposioApp = Literal[
    "gmail",
    "google_calendar",
    "notion",
    "trello",
    "asana",
    "superhuman",
    "granola",
    "slack",
    "hubspot",
    "salesforce",
]


class PrimaryContact(BaseModel):
    name: str
    email: str
    phone: str | None = None


class CustomerInfo(BaseModel):
    slug: str
    legal_name: str
    primary_contact: PrimaryContact
    vertical: Vertical
    sub_niche: str | None = None
    timezone: str = "America/Los_Angeles"

    @field_validator("slug")
    @classmethod
    def slug_format(cls, v: str) -> str:
        if not v.replace("-", "").isalnum() or v != v.lower():
            raise ValueError("slug must be lowercase alphanumeric with hyphens only")
        return v


class UnlimitedOffer(BaseModel):
    agents: bool = True
    usage: bool = True
    monitoring: bool = True
    security: bool = True
    ongoing_changes: bool = True


class Contract(BaseModel):
    tier: Tier
    start_date: str
    billing_cycle: Literal["monthly", "annual"] = "monthly"
    unlimited: UnlimitedOffer = Field(default_factory=UnlimitedOffer)


class SecondBrain(BaseModel):
    enabled: bool = False
    seed_path: str | None = None


class AgentDef(BaseModel):
    name: str
    runtime: Tier
    role: str
    mcps: list[MCPName] = Field(default_factory=list)
    connectors: list[ConnectorName] = Field(default_factory=list)
    composio_apps: list[ComposioApp] = Field(default_factory=list)
    second_brain: SecondBrain = Field(default_factory=SecondBrain)


class Surface(BaseModel):
    telegram_channel: bool = True
    weekly_loom_digest: bool = False
    trello_board: bool = False
    granola_meeting_notes: bool = False


class Observability(BaseModel):
    watchdog_interval_seconds: int = 300
    alert_channels: list[Literal["email", "telegram"]] = Field(
        default_factory=lambda: ["email", "telegram"]
    )
    health_digest_cadence: Literal["daily", "weekly"] = "daily"
    health_digest_time: str = "08:00"


class CustomerConfig(BaseModel):
    """The full customer config loaded from YAML."""

    customer: CustomerInfo
    contract: Contract
    agents: list[AgentDef]
    surface: Surface = Field(default_factory=Surface)
    observability: Observability = Field(default_factory=Observability)
    operator_notes: str | None = None

    @classmethod
    def from_file(cls, path: Path) -> "CustomerConfig":
        with path.open("r") as f:
            data = yaml.safe_load(f)
        return cls(**data)


# ---------------------------------------------------------------------------
# Stack definitions
# ---------------------------------------------------------------------------
class StackResources(BaseModel):
    cpu_vcpus: int
    memory_gb: int
    disk_gb: int
    network_egress_gb: int


class StackConfig(BaseModel):
    stack: Tier
    display_name: str
    monthly_price_usd: int
    runtime: dict
    models: dict
    mcps: list[dict]
    connectors: list[dict]
    second_brain: dict
    observability: dict
    resources: StackResources

    @classmethod
    def load(cls, tier: Tier) -> "StackConfig":
        path = STACKS_DIR / f"{tier}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Stack definition missing: {path}")
        with path.open("r") as f:
            data = yaml.safe_load(f)
        return cls(**data)


# ---------------------------------------------------------------------------
# Customer discovery
# ---------------------------------------------------------------------------
def list_customers() -> list[str]:
    """Return slugs of all configured customers."""
    if not CUSTOMERS_DIR.exists():
        return []
    return sorted(p.stem for p in CUSTOMERS_DIR.glob("*.yaml"))


def load_customer(slug: str) -> CustomerConfig:
    """Load a customer config by slug."""
    path = CUSTOMERS_DIR / f"{slug}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No config for customer '{slug}' at {path}")
    return CustomerConfig.from_file(path)
