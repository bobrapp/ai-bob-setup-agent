"""Profile management for the personal + foundation automation system.

Supports versioned profiles per operator (bob.v1.yaml, ken.v1.yaml, etc.)
so each person can stage changes, add workflows, and roll back independently.

INTERNAL USE ONLY.
"""

from __future__ import annotations

import glob
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.personal_foundation.config import PERSONAL_FOUNDATION_CONFIG_DIR

PROFILES_DIR = PERSONAL_FOUNDATION_CONFIG_DIR / "profiles"


@dataclass
class AgentConfig:
    """Configuration for a single agent within a profile."""
    name: str
    enabled: bool
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class Workflow:
    """A named workflow with trigger and steps."""
    name: str
    trigger: str
    steps: list[str] = field(default_factory=list)


@dataclass
class Profile:
    """A versioned operator profile."""
    name: str
    email: str
    version: str
    stage: str  # "staging" or "production"
    timezone: str
    agents: dict[str, AgentConfig] = field(default_factory=dict)
    integrations: dict[str, bool] = field(default_factory=dict)
    workflows: list[Workflow] = field(default_factory=list)
    outreach: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_production(self) -> bool:
        return self.stage == "production"

    @property
    def is_staging(self) -> bool:
        return self.stage == "staging"

    @property
    def enabled_agents(self) -> list[str]:
        return [name for name, ac in self.agents.items() if ac.enabled]

    @property
    def disabled_agents(self) -> list[str]:
        return [name for name, ac in self.agents.items() if not ac.enabled]

    @property
    def enabled_integrations(self) -> list[str]:
        return [name for name, enabled in self.integrations.items() if enabled]


def load_profile(operator: str, version: str | None = None) -> Profile:
    """Load a profile by operator name and optional version.

    If version is None, loads the latest version.
    Raises FileNotFoundError if no profile exists.
    """
    if version:
        path = PROFILES_DIR / f"{operator}.v{version}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Profile not found: {path}")
    else:
        # Find latest version
        pattern = str(PROFILES_DIR / f"{operator}.v*.yaml")
        matches = sorted(glob.glob(pattern))
        if not matches:
            raise FileNotFoundError(
                f"No profiles found for operator '{operator}' in {PROFILES_DIR}"
            )
        path = Path(matches[-1])  # Latest version (lexicographic sort)

    with path.open("r") as f:
        data = yaml.safe_load(f)

    return _parse_profile(data, path)


def list_profiles() -> list[dict[str, str]]:
    """List all available profiles with their versions and stages."""
    if not PROFILES_DIR.exists():
        return []

    profiles = []
    for path in sorted(PROFILES_DIR.glob("*.yaml")):
        try:
            with path.open("r") as f:
                data = yaml.safe_load(f)
            p = data.get("profile", {})
            profiles.append({
                "file": path.name,
                "operator": path.stem.split(".")[0],
                "version": p.get("version", "unknown"),
                "stage": p.get("stage", "unknown"),
                "name": p.get("name", "unknown"),
            })
        except Exception:
            continue

    return profiles


def promote_to_production(operator: str, version: str) -> Profile:
    """Promote a staging profile to production.

    Returns the updated profile.
    """
    profile = load_profile(operator, version)
    if profile.is_production:
        return profile  # Already production

    # Update the file
    path = PROFILES_DIR / f"{operator}.v{version}.yaml"
    with path.open("r") as f:
        data = yaml.safe_load(f)

    data["profile"]["stage"] = "production"

    with path.open("w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    profile.stage = "production"
    return profile


def _parse_profile(data: dict, path: Path) -> Profile:
    """Parse raw YAML data into a Profile dataclass."""
    p = data.get("profile", {})

    agents = {}
    for agent_name, agent_data in data.get("agents", {}).items():
        agents[agent_name] = AgentConfig(
            name=agent_name,
            enabled=agent_data.get("enabled", False),
            config=agent_data.get("config", {}),
        )

    workflows = []
    for wf in data.get("workflows", []):
        workflows.append(Workflow(
            name=wf.get("name", ""),
            trigger=wf.get("trigger", ""),
            steps=wf.get("steps", []),
        ))

    return Profile(
        name=p.get("name", ""),
        email=p.get("email", ""),
        version=p.get("version", "1.0.0"),
        stage=p.get("stage", "staging"),
        timezone=p.get("timezone", "America/Los_Angeles"),
        agents=agents,
        integrations=data.get("integrations", {}),
        workflows=workflows,
        outreach=data.get("outreach", {}),
        raw=data,
    )
