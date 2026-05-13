"""Smoke tests — make sure the basic plumbing works.

Run with: `pytest tests -v`
"""

from __future__ import annotations


import pytest
import yaml

from src.config import (
    REPO_ROOT,
    STACKS_DIR,
    CustomerConfig,
    StackConfig,
    check_env,
)
from src.hermes_install import HermesInstaller
from src.mcp_config import MCP_REGISTRY, MCPInstaller
from src.orgo_client import CloudComputer, OrgoClient
from src.telegram_meta import TelegramConfig, TelegramMeta


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------
def test_example_customer_yaml_parses() -> None:
    example = REPO_ROOT / "config" / "customers.example.yaml"
    with example.open("r") as f:
        data = yaml.safe_load(f)
    cc = CustomerConfig(**data)
    assert cc.customer.slug == "acme-marketing"
    assert cc.contract.tier in {"hermes", "openclaw"}
    assert len(cc.agents) >= 1
    assert all(a.runtime in {"hermes", "openclaw"} for a in cc.agents)


def test_stack_definitions_load() -> None:
    for tier in ("hermes", "openclaw"):
        s = StackConfig.load(tier)  # type: ignore[arg-type]
        assert s.stack == tier
        assert s.monthly_price_usd > 0
        assert "primary" in s.models
        assert "base_image" in s.runtime


def test_stack_files_exist() -> None:
    assert (STACKS_DIR / "hermes.yaml").exists()
    assert (STACKS_DIR / "openclaw.yaml").exists()


def test_pricing_per_video_source() -> None:
    """Per Nick: OpenClaw ~$5K/mo, Hermes ~$10K/mo."""
    hermes = StackConfig.load("hermes")  # type: ignore[arg-type]
    openclaw = StackConfig.load("openclaw")  # type: ignore[arg-type]
    assert hermes.monthly_price_usd == 10_000
    assert openclaw.monthly_price_usd == 5_000


# ---------------------------------------------------------------------------
# Env doctor
# ---------------------------------------------------------------------------
def test_check_env_returns_structured_result() -> None:
    result = check_env()
    assert "required" in result
    assert "optional" in result
    assert isinstance(result["required"], list)
    assert isinstance(result["optional"], list)


# ---------------------------------------------------------------------------
# Orgo client (dry-run)
# ---------------------------------------------------------------------------
def test_orgo_dry_run_does_not_require_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORGO_API_KEY", raising=False)
    client = OrgoClient(dry_run=True)
    assert client.dry_run is True


def test_orgo_real_mode_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORGO_API_KEY", raising=False)
    with pytest.raises(Exception):  # OrgoError
        OrgoClient(dry_run=False)


def test_ensure_workspace_idempotent_dry_run() -> None:
    client = OrgoClient(api_key="dummy", dry_run=True)
    ws1 = client.ensure_workspace("test-customer")
    ws2 = client.ensure_workspace("test-customer")
    # Dry-run returns deterministic stub IDs
    assert ws1.customer_slug == ws2.customer_slug == "test-customer"


# ---------------------------------------------------------------------------
# MCP
# ---------------------------------------------------------------------------
def test_mcp_registry_has_all_video_mcps() -> None:
    """Per Nick: Perplexity, Context7, X MCP."""
    assert "perplexity" in MCP_REGISTRY
    assert "context7" in MCP_REGISTRY
    assert "x_mcp" in MCP_REGISTRY


def test_mcp_registry_includes_orgo() -> None:
    """Orgo MCP from Nick's orgo-mcp repo."""
    assert "orgo" in MCP_REGISTRY


def test_composio_apps_on_example_customer() -> None:
    """Verify composio_apps are parsed from customer YAML."""
    example = REPO_ROOT / "config" / "customers.example.yaml"
    with example.open("r") as f:
        data = yaml.safe_load(f)
    cc = CustomerConfig(**data)
    # At least one agent should have composio_apps
    agents_with_apps = [a for a in cc.agents if a.composio_apps]
    assert len(agents_with_apps) >= 1


def test_mcp_install_dry_run_does_not_crash() -> None:
    installer = MCPInstaller(dry_run=True)
    cc = CloudComputer(
        id="cc_test",
        workspace_id="ws_test",
        agent_name="a",
        image="img",
        status="running",
    )
    installer.install(cc, "perplexity")
    installer.install(cc, "context7")
    installer.install(cc, "x_mcp")


# ---------------------------------------------------------------------------
# Telegram (no credentials needed for dry run)
# ---------------------------------------------------------------------------
def test_telegram_unconfigured_does_not_crash() -> None:
    cfg = TelegramConfig(bot_token="", control_chat_id="")
    tm = TelegramMeta(config=cfg, dry_run=False)
    assert tm.send("hello") is False  # quiet failure
    assert cfg.configured is False


def test_telegram_dry_run_sends_ok() -> None:
    cfg = TelegramConfig(bot_token="t", control_chat_id="c")
    tm = TelegramMeta(config=cfg, dry_run=True)
    assert tm.send("hello") is True


# ---------------------------------------------------------------------------
# Full provisioning (dry run)
# ---------------------------------------------------------------------------
def test_full_onboard_dry_run() -> None:
    """End-to-end dry-run onboarding: parses YAML, walks the orchestration path,
    produces InstallResult per agent. No real API calls."""
    example_yaml = REPO_ROOT / "config" / "customers.example.yaml"
    with example_yaml.open("r") as f:
        data = yaml.safe_load(f)
    customer = CustomerConfig(**data)

    orgo = OrgoClient(api_key="dummy", dry_run=True)
    installer = HermesInstaller(orgo, dry_run=True)
    workspace = orgo.ensure_workspace(customer.customer.slug)

    results = []
    for agent in customer.agents:
        stack = StackConfig.load(agent.runtime)
        cc = orgo.ensure_cloud_computer(
            workspace_id=workspace.id,
            agent_name=agent.name,
            image=stack.runtime["base_image"],
        )
        results.append(installer.install(cc, agent, stack))

    assert len(results) == len(customer.agents)
    for r in results:
        assert r.runtime in {"hermes", "openclaw"}
        assert r.cloud_computer_id  # not empty
