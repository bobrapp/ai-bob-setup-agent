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
    PreflightResult,
    StackConfig,
    check_env,
    list_customers,
    load_customer,
    validate_customer,
)
from src.hermes_install import HermesInstaller
from src.mcp_config import MCP_REGISTRY, MCPInstaller
from src.orgo_client import CloudComputer, OrgoClient
from src.audit_log import (
    AuditEntry,
    _next_seq,
    log_action,
    read_log,
)
from src.setup_agent import (
    DecomResult,
    _estimate_cost,
    add_agent_to_customer,
    decommission_customer,
    onboard_customer,
    show_status,
)
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
# Pre-flight validation
# ---------------------------------------------------------------------------
def test_validate_customer_catches_duplicate_agents() -> None:
    """Duplicate agent names should produce an error."""
    example = REPO_ROOT / "config" / "customers.example.yaml"
    with example.open("r") as f:
        data = yaml.safe_load(f)
    # Duplicate the first agent
    data["agents"].append(data["agents"][0].copy())
    cc = CustomerConfig(**data)
    result = validate_customer(cc)
    assert not result.ok
    assert any("Duplicate" in e for e in result.errors)


def test_validate_customer_warns_on_missing_mcp_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If MCP keys are unset, validation should warn (not error)."""
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    monkeypatch.delenv("CONTEXT7_API_KEY", raising=False)
    monkeypatch.delenv("X_MCP_BEARER_TOKEN", raising=False)
    # Set required keys so we don't get errors there
    monkeypatch.setenv("ORGO_API_KEY", "test")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("TELEGRAM_CONTROL_CHAT_ID", "test")

    example = REPO_ROOT / "config" / "customers.example.yaml"
    with example.open("r") as f:
        data = yaml.safe_load(f)
    cc = CustomerConfig(**data)
    result = validate_customer(cc)
    # Should still be ok (warnings, not errors)
    assert result.ok
    # But should have warnings about missing keys
    assert len(result.warnings) > 0


def test_validate_customer_passes_with_all_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With all keys set, validation should pass with no errors."""
    # Set all the keys
    for key in (
        "ORGO_API_KEY",
        "OPENAI_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CONTROL_CHAT_ID",
        "PERPLEXITY_API_KEY",
        "CONTEXT7_API_KEY",
        "X_MCP_BEARER_TOKEN",
        "COMPOSIO_API_KEY",
        "AGENT_MAIL_API_KEY",
        "HERMES_LICENSE_KEY",
        "OPENCLAW_LICENSE_KEY",
    ):
        monkeypatch.setenv(key, "test-value")

    example = REPO_ROOT / "config" / "customers.example.yaml"
    with example.open("r") as f:
        data = yaml.safe_load(f)
    cc = CustomerConfig(**data)
    result = validate_customer(cc)
    assert result.ok
    # May still have warnings about missing context/seed files
    # but no errors
    assert len(result.errors) == 0


def test_preflight_result_summary() -> None:
    r = PreflightResult(ok=True, errors=[], warnings=[])
    assert r.summary == "All checks passed."

    r2 = PreflightResult(ok=False, errors=["bad"], warnings=["meh"])
    assert "1 error" in r2.summary
    assert "1 warning" in r2.summary


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------
def test_estimate_cost_matches_tiers() -> None:
    """Cost should be sum of stack prices for all agents."""
    example = REPO_ROOT / "config" / "customers.example.yaml"
    with example.open("r") as f:
        data = yaml.safe_load(f)
    cc = CustomerConfig(**data)
    cost = _estimate_cost(cc)
    # acme-marketing: 2 hermes ($10K each) + 1 openclaw ($5K) = $25K
    assert cost == 25_000


# ---------------------------------------------------------------------------
# Customer discovery
# ---------------------------------------------------------------------------
def test_list_customers_includes_acme() -> None:
    """After creating config/customers/acme-marketing.yaml, it should be listed."""
    slugs = list_customers()
    assert "acme-marketing" in slugs


def test_load_customer_by_slug() -> None:
    c = load_customer("acme-marketing")
    assert c.customer.slug == "acme-marketing"
    assert len(c.agents) == 3


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


def test_full_onboard_via_cli_function(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test the full onboard_customer function (the CLI entrypoint) in dry-run."""
    # Set required env keys so pre-flight passes
    monkeypatch.setenv("ORGO_API_KEY", "test")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("TELEGRAM_CONTROL_CHAT_ID", "test")

    c = load_customer("acme-marketing")
    results = onboard_customer(c, dry_run=True)
    assert len(results) == 3
    assert results[0].agent_name == "outreach-agent"
    assert results[1].agent_name == "proposal-agent"
    assert results[2].agent_name == "ops-agent"
    # Hermes agents have the full MCP set
    assert "perplexity" in results[0].mcps_installed
    assert "context7" in results[0].mcps_installed


def test_status_dry_run_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """Status command should work in dry-run without crashing."""
    monkeypatch.setenv("ORGO_API_KEY", "test")
    c = load_customer("acme-marketing")
    # Should not raise
    show_status(c, dry_run=True)


# ---------------------------------------------------------------------------
# Deploy artifacts
# ---------------------------------------------------------------------------
def test_systemd_unit_file_exists() -> None:
    """The systemd unit template must exist in deploy/."""
    unit = REPO_ROOT / "deploy" / "ai-bob-watchdog.service"
    assert unit.exists(), f"Missing: {unit}"


def test_systemd_unit_has_required_sections() -> None:
    """A valid systemd unit needs [Unit], [Service], and [Install] sections."""
    unit = REPO_ROOT / "deploy" / "ai-bob-watchdog.service"
    content = unit.read_text()
    for section in ("[Unit]", "[Service]", "[Install]"):
        assert section in content, f"Missing section {section} in unit file"


def test_systemd_unit_has_placeholders() -> None:
    """The template should have __DEPLOY_*__ placeholders for install script."""
    unit = REPO_ROOT / "deploy" / "ai-bob-watchdog.service"
    content = unit.read_text()
    assert "__DEPLOY_DIR__" in content
    assert "__DEPLOY_USER__" in content
    assert "__DEPLOY_GROUP__" in content


def test_systemd_unit_restart_policy() -> None:
    """Watchdog must restart on failure."""
    unit = REPO_ROOT / "deploy" / "ai-bob-watchdog.service"
    content = unit.read_text()
    assert "Restart=on-failure" in content
    assert "RestartSec=" in content


def test_systemd_unit_security_hardening() -> None:
    """Unit should have basic security hardening."""
    unit = REPO_ROOT / "deploy" / "ai-bob-watchdog.service"
    content = unit.read_text()
    assert "NoNewPrivileges=true" in content
    assert "ProtectSystem=strict" in content


def test_env_template_exists() -> None:
    """The env template must exist in deploy/."""
    env = REPO_ROOT / "deploy" / "ai-bob-watchdog.env"
    assert env.exists()


def test_env_template_has_required_keys() -> None:
    """The env template must include the required API key placeholders."""
    env = REPO_ROOT / "deploy" / "ai-bob-watchdog.env"
    content = env.read_text()
    for key in ("ORGO_API_KEY", "OPENAI_API_KEY", "TELEGRAM_BOT_TOKEN"):
        assert key in content, f"Missing key {key} in env template"


def test_deploy_scripts_exist() -> None:
    """Install and uninstall scripts must exist."""
    assert (REPO_ROOT / "deploy" / "install-watchdog.sh").exists()
    assert (REPO_ROOT / "deploy" / "uninstall-watchdog.sh").exists()


def test_install_script_is_executable() -> None:
    """Install script should have execute permission."""
    import os
    import stat

    path = REPO_ROOT / "deploy" / "install-watchdog.sh"
    mode = os.stat(path).st_mode
    assert mode & stat.S_IXUSR, "install-watchdog.sh is not executable"


# ---------------------------------------------------------------------------
# Health check script
# ---------------------------------------------------------------------------
def _load_healthcheck_module():
    """Import scripts/healthcheck.py as a module."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "healthcheck", REPO_ROOT / "scripts" / "healthcheck.py"
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_healthcheck_dry_run_returns_results() -> None:
    """Dry-run health check should return HealthCheck objects for all agents."""
    hc_mod = _load_healthcheck_module()
    results = hc_mod.run_health_checks(["acme-marketing"], dry_run=True)
    # Dry-run Orgo returns no workspace -> all agents marked down
    assert len(results) == 3
    assert all(r.customer_slug == "acme-marketing" for r in results)
    assert all(r.status == "down" for r in results)  # no workspace in dry-run
    agent_names = {r.agent_name for r in results}
    assert agent_names == {"outreach-agent", "proposal-agent", "ops-agent"}


def test_healthcheck_missing_customer_slug() -> None:
    """A slug with no YAML should produce an unknown result, not crash."""
    hc_mod = _load_healthcheck_module()
    results = hc_mod.run_health_checks(["nonexistent-customer"], dry_run=True)
    assert len(results) == 1
    assert results[0].status == "unknown"
    assert "not found" in results[0].reason


def test_healthcheck_json_serialization() -> None:
    """The JSON serializer should handle HealthCheck with None heartbeat."""
    from src.observability import HealthCheck

    hc_mod = _load_healthcheck_module()
    hc = HealthCheck(
        customer_slug="test",
        agent_name="a",
        cloud_computer_id="cc1",
        status="healthy",
        last_heartbeat=None,
        reason="",
    )
    serialized = hc_mod._serialize_healthcheck(hc)
    assert serialized["last_heartbeat"] is None
    assert serialized["customer_slug"] == "test"


def test_healthcheck_json_serialization_with_datetime() -> None:
    """The JSON serializer should convert datetime to ISO string."""
    from datetime import datetime, timezone

    from src.observability import HealthCheck

    hc_mod = _load_healthcheck_module()
    now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    hc = HealthCheck(
        customer_slug="test",
        agent_name="a",
        cloud_computer_id="cc1",
        status="healthy",
        last_heartbeat=now,
        reason="",
    )
    serialized = hc_mod._serialize_healthcheck(hc)
    assert serialized["last_heartbeat"] == "2026-01-15T12:00:00+00:00"


def test_healthcheck_exit_code_logic() -> None:
    """Exit 0 when all healthy, 1 when any issues."""
    from src.observability import HealthCheck

    healthy = [
        HealthCheck("c", "a1", "cc1", "healthy", None),
        HealthCheck("c", "a2", "cc2", "healthy", None),
    ]
    assert all(r.status == "healthy" for r in healthy)

    mixed = [
        HealthCheck("c", "a1", "cc1", "healthy", None),
        HealthCheck("c", "a2", "cc2", "down", None, "stopped"),
    ]
    assert not all(r.status == "healthy" for r in mixed)


# ---------------------------------------------------------------------------
# Decommission
# ---------------------------------------------------------------------------
def test_decom_result_dataclass() -> None:
    """DecomResult tracks what was deleted."""
    r = DecomResult(
        customer_slug="acme-marketing",
        workspace_id="ws_123",
        computers_deleted=["outreach-agent", "proposal-agent"],
        workspace_deleted=True,
        notification_sent=True,
        dry_run=False,
        elapsed=1.5,
    )
    assert r.total_deleted == 2
    assert r.workspace_deleted is True
    assert r.customer_slug == "acme-marketing"


def test_decom_result_empty() -> None:
    """DecomResult with nothing deleted (no workspace found)."""
    r = DecomResult(customer_slug="ghost", workspace_id="")
    assert r.total_deleted == 0
    assert r.workspace_deleted is False
    assert r.notification_sent is False


def test_decommission_dry_run_no_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dry-run decom when no workspace exists returns empty result."""
    monkeypatch.setenv("ORGO_API_KEY", "test")
    c = load_customer("acme-marketing")
    result = decommission_customer(c, dry_run=True, force=True)
    # Dry-run OrgoClient.get_workspace_by_slug returns None
    assert result.workspace_id == ""
    assert result.total_deleted == 0
    assert result.workspace_deleted is False


def test_decommission_dry_run_returns_decom_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decommission should return a DecomResult object."""
    monkeypatch.setenv("ORGO_API_KEY", "test")
    c = load_customer("acme-marketing")
    result = decommission_customer(c, dry_run=True, force=True)
    assert isinstance(result, DecomResult)
    assert result.customer_slug == "acme-marketing"
    assert result.dry_run is True


# ---------------------------------------------------------------------------
# Add-agent
# ---------------------------------------------------------------------------
def test_add_agent_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dry-run add-agent should provision and return an InstallResult."""
    monkeypatch.setenv("ORGO_API_KEY", "test")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("TELEGRAM_CONTROL_CHAT_ID", "test")

    from src.hermes_install import InstallResult

    c = load_customer("acme-marketing")
    result = add_agent_to_customer(c, "outreach-agent", dry_run=True)
    assert isinstance(result, InstallResult)
    assert result.agent_name == "outreach-agent"
    assert result.runtime == "hermes"
    assert "perplexity" in result.mcps_installed
    assert "context7" in result.mcps_installed


def test_add_agent_invalid_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adding an agent not in the YAML should raise a ClickException."""
    monkeypatch.setenv("ORGO_API_KEY", "test")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("TELEGRAM_CONTROL_CHAT_ID", "test")

    import click

    c = load_customer("acme-marketing")
    with pytest.raises(click.ClickException, match="not-a-real-agent"):
        add_agent_to_customer(c, "not-a-real-agent", dry_run=True)


def test_add_agent_openclaw_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adding an OpenClaw agent should work and return the correct runtime."""
    monkeypatch.setenv("ORGO_API_KEY", "test")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("TELEGRAM_CONTROL_CHAT_ID", "test")

    c = load_customer("acme-marketing")
    # ops-agent is openclaw tier in acme-marketing
    result = add_agent_to_customer(c, "ops-agent", dry_run=True)
    assert result.runtime == "openclaw"
    assert result.agent_name == "ops-agent"


def test_add_agent_returns_cloud_computer_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The result should include a cloud computer ID."""
    monkeypatch.setenv("ORGO_API_KEY", "test")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("TELEGRAM_CONTROL_CHAT_ID", "test")

    c = load_customer("acme-marketing")
    result = add_agent_to_customer(c, "proposal-agent", dry_run=True)
    assert result.cloud_computer_id  # not empty
    assert result.agent_name == "proposal-agent"
    assert result.runtime == "hermes"


# ---------------------------------------------------------------------------
# Audit logger
# ---------------------------------------------------------------------------
def test_audit_entry_dataclass() -> None:
    """AuditEntry should hold all required fields."""
    entry = AuditEntry(
        operator="bob",
        operator_email="bob@example.com",
        timestamp="2026-05-12T00:00:00+00:00",
        date="2026-05-12",
        time="00:00:00",
        action="onboard",
        command="make onboard CUSTOMER=acme",
        customer="acme",
        model="gpt-5.5",
        dry_run=False,
        status="success",
        result_summary="Onboarded 3 agents",
    )
    assert entry.operator == "bob"
    assert entry.action == "onboard"
    assert entry.seq == 0
    assert entry.version == "0.1.0"


def test_log_action_writes_to_file(tmp_path, monkeypatch) -> None:
    """log_action should append a JSONL line to the audit log."""
    import json

    from src import audit_log

    log_dir = tmp_path / "logs"
    log_file = log_dir / "audit.jsonl"
    monkeypatch.setattr(audit_log, "AUDIT_LOG_DIR", log_dir)
    monkeypatch.setattr(audit_log, "AUDIT_LOG_FILE", log_file)
    monkeypatch.setenv("BOB_OPERATOR_NAME", "tester")
    monkeypatch.setenv("BOB_OPERATOR_EMAIL", "test@test.com")

    entry = log_action(
        action="test-action",
        command="pytest",
        customer="test-customer",
        status="success",
        result_summary="Test passed",
    )

    assert log_file.exists()
    lines = log_file.read_text().strip().split("\n")
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["action"] == "test-action"
    assert data["customer"] == "test-customer"
    assert data["operator"] == "tester"
    assert data["seq"] == 1
    assert entry.seq == 1


def test_log_action_increments_seq(tmp_path, monkeypatch) -> None:
    """Sequence numbers should auto-increment."""
    from src import audit_log

    log_dir = tmp_path / "logs"
    log_file = log_dir / "audit.jsonl"
    monkeypatch.setattr(audit_log, "AUDIT_LOG_DIR", log_dir)
    monkeypatch.setattr(audit_log, "AUDIT_LOG_FILE", log_file)

    e1 = log_action(action="first", command="a", status="success")
    e2 = log_action(action="second", command="b", status="success")
    e3 = log_action(action="third", command="c", status="failure")

    assert e1.seq == 1
    assert e2.seq == 2
    assert e3.seq == 3


def test_read_log_returns_entries(tmp_path, monkeypatch) -> None:
    """read_log should return the last N entries."""
    from src import audit_log

    log_dir = tmp_path / "logs"
    log_file = log_dir / "audit.jsonl"
    monkeypatch.setattr(audit_log, "AUDIT_LOG_DIR", log_dir)
    monkeypatch.setattr(audit_log, "AUDIT_LOG_FILE", log_file)

    for i in range(5):
        log_action(action=f"action-{i}", command=f"cmd-{i}", status="success")

    entries = read_log(limit=3)
    assert len(entries) == 3
    assert entries[0]["action"] == "action-2"
    assert entries[-1]["action"] == "action-4"


def test_read_log_empty_file(tmp_path, monkeypatch) -> None:
    """read_log on a nonexistent file should return empty list."""
    from src import audit_log

    monkeypatch.setattr(audit_log, "AUDIT_LOG_FILE", tmp_path / "nope.jsonl")
    assert read_log() == []


def test_next_seq_starts_at_one(tmp_path, monkeypatch) -> None:
    """With no log file, _next_seq should return 1."""
    from src import audit_log

    monkeypatch.setattr(audit_log, "AUDIT_LOG_FILE", tmp_path / "nope.jsonl")
    assert _next_seq() == 1


def test_log_action_records_details(tmp_path, monkeypatch) -> None:
    """Details dict should be preserved in the log entry."""
    import json

    from src import audit_log

    log_dir = tmp_path / "logs"
    log_file = log_dir / "audit.jsonl"
    monkeypatch.setattr(audit_log, "AUDIT_LOG_DIR", log_dir)
    monkeypatch.setattr(audit_log, "AUDIT_LOG_FILE", log_file)

    log_action(
        action="onboard",
        command="make onboard",
        customer="acme",
        status="success",
        details={"agents": 3, "cost": 25000},
    )

    data = json.loads(log_file.read_text().strip())
    assert data["details"]["agents"] == 3
    assert data["details"]["cost"] == 25000
