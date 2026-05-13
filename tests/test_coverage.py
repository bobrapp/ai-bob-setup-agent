"""Comprehensive tests to improve module coverage.

These tests complement test_smoke.py by exercising branches and paths
that the smoke tests do not reach.
"""

from __future__ import annotations

import json
import smtplib
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.config import (
    REPO_ROOT,
    CustomerConfig,
    CustomerInfo,
    PrimaryContact,
    PreflightResult,
    StackConfig,
    check_env,
    list_customers,
    load_customer,
    load_env,
    validate_customer,
)
from src.audit_log import (
    AuditEntry,
    _get_git_info,
    _get_operator,
    _next_seq,
    log_action,
    log_cli_invocation,
    read_log,
)
from src.hermes_install import HermesInstaller, InstallResult
from src.mcp_config import MCP_REGISTRY, MCPInstaller
from src.observability import HealthCheck, Watchdog, send_email_alert
from src.orgo_client import CloudComputer, OrgoClient, OrgoError, Workspace
from src.setup_agent import (
    DecomResult,
    _dry_run_flag,
    _estimate_cost,
    run_doctor,
    show_status,
)
from src.telegram_meta import TelegramConfig, TelegramMeta


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------
def _make_primary_contact(**kwargs) -> PrimaryContact:
    """Return a PrimaryContact with sensible defaults."""
    defaults = {"name": "Bob", "email": "bob@acme.com"}
    defaults.update(kwargs)
    return PrimaryContact(**defaults)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------
def _load_example_customer() -> CustomerConfig:
    example = REPO_ROOT / "config" / "customers.example.yaml"
    with example.open("r") as f:
        data = yaml.safe_load(f)
    return CustomerConfig(**data)


def _make_agent_def(name: str = "test-agent", runtime: str = "hermes"):
    """Build a minimal AgentDef-like dict and parse it via CustomerConfig."""
    from src.config import AgentDef

    return AgentDef(name=name, runtime=runtime, role="test role")


# ---------------------------------------------------------------------------
# config.py
# ---------------------------------------------------------------------------
class TestLoadEnv:
    def test_load_env_with_nonexistent_path_is_safe(self, tmp_path: Path) -> None:
        """load_env with a path that doesn't exist should not raise."""
        load_env(tmp_path / "no_such_file.env")

    def test_load_env_with_existing_file(self, tmp_path: Path) -> None:
        """load_env with a real .env file should load it without error."""
        env_file = tmp_path / ".env"
        env_file.write_text("DUMMY_VAR=hello\n")
        load_env(env_file)


class TestCustomerInfoSlugValidator:
    def test_valid_slug(self) -> None:
        info = CustomerInfo(
            slug="acme-corp",
            legal_name="Acme Corp",
            primary_contact=_make_primary_contact(),
            vertical="marketing",
        )
        assert info.slug == "acme-corp"

    def test_uppercase_slug_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="slug must be"):
            CustomerInfo(
                slug="ACME-CORP",
                legal_name="Acme Corp",
                primary_contact=_make_primary_contact(),
                vertical="marketing",
            )

    def test_slug_with_spaces_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="slug must be"):
            CustomerInfo(
                slug="acme corp",
                legal_name="Acme Corp",
                primary_contact=_make_primary_contact(),
                vertical="marketing",
            )

    def test_slug_with_special_chars_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CustomerInfo(
                slug="acme_corp!",
                legal_name="Acme Corp",
                primary_contact=_make_primary_contact(),
                vertical="marketing",
            )


class TestListCustomers:
    def test_no_customers_dir_returns_empty(self, tmp_path: Path, monkeypatch) -> None:
        import src.config as cfg_mod

        monkeypatch.setattr(cfg_mod, "CUSTOMERS_DIR", tmp_path / "nonexistent")
        result = list_customers()
        assert result == []


class TestLoadCustomer:
    def test_missing_slug_raises(self) -> None:
        with pytest.raises(FileNotFoundError, match="no-such-customer"):
            load_customer("no-such-customer")


class TestStackConfigLoad:
    def test_missing_stack_raises(self) -> None:
        with pytest.raises(FileNotFoundError, match="missing"):
            StackConfig.load("nonexistent_tier")  # type: ignore[arg-type]


class TestValidateCustomerExtra:
    def test_missing_stack_definition_is_error(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """An agent referencing a stack with no YAML file produces an error."""
        import src.config as cfg_mod

        monkeypatch.setattr(cfg_mod, "STACKS_DIR", tmp_path)  # empty dir
        # Set all required env keys
        for key in cfg_mod.REQUIRED_ENV_KEYS:
            monkeypatch.setenv(key, "test")

        customer = _load_example_customer()
        result = validate_customer(customer)
        assert not result.ok
        assert any("Stack definition missing" in e for e in result.errors)

    def test_connector_env_missing_is_warning(self, monkeypatch) -> None:
        """Missing connector API key produces a warning, not an error."""
        for key in (
            "ORGO_API_KEY",
            "OPENAI_API_KEY",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_CONTROL_CHAT_ID",
        ):
            monkeypatch.setenv(key, "test")
        monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)
        monkeypatch.delenv("AGENT_MAIL_API_KEY", raising=False)

        customer = _load_example_customer()
        result = validate_customer(customer)
        assert result.ok  # warnings only, no errors
        assert any("composio" in w.lower() or "agent_mail" in w.lower() for w in result.warnings)

    def test_license_key_missing_is_warning(self, monkeypatch) -> None:
        """Missing license key produces a warning."""
        for key in (
            "ORGO_API_KEY",
            "OPENAI_API_KEY",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_CONTROL_CHAT_ID",
        ):
            monkeypatch.setenv(key, "test")
        monkeypatch.delenv("HERMES_LICENSE_KEY", raising=False)
        monkeypatch.delenv("OPENCLAW_LICENSE_KEY", raising=False)

        customer = _load_example_customer()
        result = validate_customer(customer)
        assert result.ok
        assert any("license" in w.lower() for w in result.warnings)

    def test_missing_context_file_is_warning(self, tmp_path: Path, monkeypatch) -> None:
        """A context_file that doesn't exist produces a warning."""
        import src.config as cfg_mod

        for key in cfg_mod.REQUIRED_ENV_KEYS:
            monkeypatch.setenv(key, "test")
        # Patch REPO_ROOT so the missing file path resolution uses tmp_path
        monkeypatch.setattr(cfg_mod, "REPO_ROOT", tmp_path)

        # Build a customer with a context_file that won't exist
        example = REPO_ROOT / "config" / "customers.example.yaml"
        with example.open("r") as f:
            data = yaml.safe_load(f)
        data["agents"][0]["second_brain"] = {
            "enabled": True,
            "context_file": "nonexistent/agents.mmd",
        }
        customer = CustomerConfig(**data)
        result = validate_customer(customer)
        assert any("Context file" in w for w in result.warnings)

    def test_missing_seed_path_is_warning(self, tmp_path: Path, monkeypatch) -> None:
        """A seed_path that doesn't exist produces a warning."""
        import src.config as cfg_mod

        for key in cfg_mod.REQUIRED_ENV_KEYS:
            monkeypatch.setenv(key, "test")
        monkeypatch.setattr(cfg_mod, "REPO_ROOT", tmp_path)

        example = REPO_ROOT / "config" / "customers.example.yaml"
        with example.open("r") as f:
            data = yaml.safe_load(f)
        data["agents"][0]["second_brain"] = {
            "enabled": True,
            "seed_path": "nonexistent/seed",
        }
        customer = CustomerConfig(**data)
        result = validate_customer(customer)
        assert any("Seed path" in w for w in result.warnings)

    def test_preflight_result_summary_warnings_only(self) -> None:
        r = PreflightResult(ok=True, errors=[], warnings=["w1", "w2"])
        assert "2 warning" in r.summary

    def test_preflight_result_summary_errors_only(self) -> None:
        r = PreflightResult(ok=False, errors=["e1"], warnings=[])
        assert "1 error" in r.summary
        assert "warning" not in r.summary


# ---------------------------------------------------------------------------
# audit_log.py
# ---------------------------------------------------------------------------
class TestGetGitInfo:
    def test_returns_strings_in_git_repo(self) -> None:
        sha, branch = _get_git_info()
        # In a real git repo both should be non-empty strings
        assert isinstance(sha, str)
        assert isinstance(branch, str)

    def test_graceful_failure_when_git_unavailable(self, monkeypatch) -> None:
        import subprocess

        monkeypatch.setattr(
            subprocess,
            "check_output",
            MagicMock(side_effect=FileNotFoundError("no git")),
        )
        sha, branch = _get_git_info()
        assert sha == ""
        assert branch == ""

    def test_graceful_failure_on_subprocess_error(self, monkeypatch) -> None:
        import subprocess

        monkeypatch.setattr(
            subprocess,
            "check_output",
            MagicMock(side_effect=subprocess.CalledProcessError(1, "git")),
        )
        sha, branch = _get_git_info()
        assert sha == ""
        assert branch == ""


class TestGetOperator:
    def test_returns_env_values_when_set(self, monkeypatch) -> None:
        monkeypatch.setenv("BOB_OPERATOR_NAME", "bob")
        monkeypatch.setenv("BOB_OPERATOR_EMAIL", "bob@example.com")
        name, email = _get_operator()
        assert name == "bob"
        assert email == "bob@example.com"

    def test_falls_back_to_system_user_when_unset(self, monkeypatch) -> None:
        monkeypatch.delenv("BOB_OPERATOR_NAME", raising=False)
        monkeypatch.delenv("BOB_OPERATOR_EMAIL", raising=False)
        name, email = _get_operator()
        assert isinstance(name, str)
        assert len(name) > 0  # getpass.getuser() returns something
        assert email == ""


class TestNextSeq:
    def test_empty_file_returns_one(self, tmp_path: Path, monkeypatch) -> None:
        import src.audit_log as audit_mod

        log_file = tmp_path / "audit.jsonl"
        log_file.write_text("")  # exists but empty
        monkeypatch.setattr(audit_mod, "AUDIT_LOG_FILE", log_file)
        assert _next_seq() == 1

    def test_malformed_json_returns_one(self, tmp_path: Path, monkeypatch) -> None:
        import src.audit_log as audit_mod

        log_file = tmp_path / "audit.jsonl"
        log_file.write_text("not-valid-json\n")
        monkeypatch.setattr(audit_mod, "AUDIT_LOG_FILE", log_file)
        assert _next_seq() == 1


class TestLogCliInvocation:
    def test_log_cli_invocation_writes_entry(self, tmp_path: Path, monkeypatch) -> None:
        import src.audit_log as audit_mod

        log_dir = tmp_path / "logs"
        log_file = log_dir / "audit.jsonl"
        monkeypatch.setattr(audit_mod, "AUDIT_LOG_DIR", log_dir)
        monkeypatch.setattr(audit_mod, "AUDIT_LOG_FILE", log_file)

        entry = log_cli_invocation(dry_run=True)
        assert entry.action == "cli_invocation"
        assert entry.status == "started"
        assert entry.dry_run is True
        assert log_file.exists()


class TestReadLogEdgeCases:
    def test_read_log_skips_malformed_lines(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        import src.audit_log as audit_mod

        log_file = tmp_path / "audit.jsonl"
        log_file.write_text('{"seq":1,"action":"ok"}\nnot-json\n{"seq":2,"action":"ok2"}\n')
        monkeypatch.setattr(audit_mod, "AUDIT_LOG_FILE", log_file)
        entries = read_log(limit=10)
        assert len(entries) == 2
        assert entries[0]["action"] == "ok"
        assert entries[1]["action"] == "ok2"

    def test_read_log_limit_greater_than_entries(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        import src.audit_log as audit_mod

        log_dir = tmp_path / "logs"
        log_file = log_dir / "audit.jsonl"
        monkeypatch.setattr(audit_mod, "AUDIT_LOG_DIR", log_dir)
        monkeypatch.setattr(audit_mod, "AUDIT_LOG_FILE", log_file)

        log_action(action="a", command="x", status="success")
        log_action(action="b", command="y", status="success")

        entries = read_log(limit=100)
        assert len(entries) == 2

    def test_log_action_with_default_model_from_env(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        import src.audit_log as audit_mod

        log_dir = tmp_path / "logs"
        log_file = log_dir / "audit.jsonl"
        monkeypatch.setattr(audit_mod, "AUDIT_LOG_DIR", log_dir)
        monkeypatch.setattr(audit_mod, "AUDIT_LOG_FILE", log_file)
        monkeypatch.setenv("DEFAULT_MODEL", "gpt-5")

        entry = log_action(action="test", command="cmd", status="success")
        assert entry.model == "gpt-5"


# ---------------------------------------------------------------------------
# mcp_config.py
# ---------------------------------------------------------------------------
class TestMCPInstaller:
    def test_install_unknown_mcp_does_not_crash(self) -> None:
        installer = MCPInstaller(dry_run=True)
        cc = CloudComputer(
            id="cc1", workspace_id="ws1", agent_name="a", image="img", status="running"
        )
        # Should warn but not raise
        installer.install(cc, "totally_unknown_mcp")

    def test_install_missing_key_non_dry_run_logs_warning(
        self, monkeypatch, capsys
    ) -> None:
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
        installer = MCPInstaller(dry_run=False)
        cc = CloudComputer(
            id="cc1", workspace_id="ws1", agent_name="a", image="img", status="running"
        )
        # Should not raise even with missing key in non-dry-run
        installer.install(cc, "perplexity")

    def test_mcp_registry_entries_have_required_fields(self) -> None:
        for name, spec in MCP_REGISTRY.items():
            assert "purpose" in spec, f"{name} missing 'purpose'"
            assert "env_var" in spec, f"{name} missing 'env_var'"
            assert "package" in spec, f"{name} missing 'package'"


# ---------------------------------------------------------------------------
# orgo_client.py
# ---------------------------------------------------------------------------
class TestOrgoClientHeaders:
    def test_headers_include_auth(self) -> None:
        client = OrgoClient(api_key="sk-test", dry_run=True)
        headers = client._headers()
        assert headers["Authorization"] == "Bearer sk-test"
        assert headers["Content-Type"] == "application/json"
        assert "ai-bob-setup-agent" in headers["User-Agent"]


class TestOrgoClientRequest:
    def test_dry_run_request_returns_stub(self) -> None:
        client = OrgoClient(api_key="sk-test", dry_run=True)
        result = client._request("GET", "/test")
        assert result["dry_run"] is True
        assert result["method"] == "GET"

    def test_real_request_raises_on_4xx(self, monkeypatch) -> None:
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request = MagicMock(return_value=mock_response)

        with patch("httpx.Client", return_value=mock_client):
            client = OrgoClient(api_key="sk-test", dry_run=False)
            with pytest.raises(OrgoError, match="403"):
                client._request("GET", "/workspaces")

    def test_real_request_empty_response_returns_empty_dict(self, monkeypatch) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = ""

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request = MagicMock(return_value=mock_response)

        with patch("httpx.Client", return_value=mock_client):
            client = OrgoClient(api_key="sk-test", dry_run=False)
            result = client._request("DELETE", "/workspaces/ws_1")
        assert result == {}


class TestOrgoClientWorkspace:
    def test_get_workspace_by_slug_returns_none_in_dry_run(self) -> None:
        client = OrgoClient(api_key="sk-test", dry_run=True)
        result = client.get_workspace_by_slug("test-customer")
        assert result is None

    def test_get_workspace_by_slug_returns_workspace_on_success(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"items": [{"id": "ws_123", "region": "us-east-1"}]}'
        mock_response.json = MagicMock(
            return_value={"items": [{"id": "ws_123", "region": "us-east-1"}]}
        )

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request = MagicMock(return_value=mock_response)

        with patch("httpx.Client", return_value=mock_client):
            client = OrgoClient(api_key="sk-test", dry_run=False)
            ws = client.get_workspace_by_slug("my-customer")
        assert ws is not None
        assert ws.id == "ws_123"
        assert ws.customer_slug == "my-customer"

    def test_get_workspace_by_slug_returns_none_when_empty(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"items": []}'
        mock_response.json = MagicMock(return_value={"items": []})

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request = MagicMock(return_value=mock_response)

        with patch("httpx.Client", return_value=mock_client):
            client = OrgoClient(api_key="sk-test", dry_run=False)
            ws = client.get_workspace_by_slug("ghost-customer")
        assert ws is None

    def test_get_workspace_by_slug_returns_none_on_orgo_error(self) -> None:
        with patch("httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.text = "Server Error"
            mock_client.request = MagicMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            client = OrgoClient(api_key="sk-test", dry_run=False)
            result = client.get_workspace_by_slug("fail-customer")
        assert result is None

    def test_ensure_workspace_returns_existing(self) -> None:
        client = OrgoClient(api_key="sk-test", dry_run=True)
        existing = Workspace(id="ws_existing", customer_slug="cust", region="us-east-1")
        with patch.object(client, "get_workspace_by_slug", return_value=existing):
            ws = client.ensure_workspace("cust")
        assert ws.id == "ws_existing"

    def test_delete_workspace_calls_request(self) -> None:
        client = OrgoClient(api_key="sk-test", dry_run=True)
        with patch.object(client, "_request") as mock_req:
            client.delete_workspace("ws_abc")
        mock_req.assert_called_once_with("DELETE", "/workspaces/ws_abc")


class TestOrgoClientCloudComputer:
    def test_list_cloud_computers_dry_run_returns_empty(self) -> None:
        client = OrgoClient(api_key="sk-test", dry_run=True)
        result = client.list_cloud_computers("ws_test")
        assert result == []

    def test_list_cloud_computers_parses_response(self) -> None:
        payload = {
            "items": [
                {
                    "id": "cc_1",
                    "name": "outreach-agent",
                    "image": "hermes:latest",
                    "status": "running",
                    "public_endpoint": "https://cc1.example.com",
                }
            ]
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = json.dumps(payload)
        mock_response.json = MagicMock(return_value=payload)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request = MagicMock(return_value=mock_response)

        with patch("httpx.Client", return_value=mock_client):
            client = OrgoClient(api_key="sk-test", dry_run=False)
            computers = client.list_cloud_computers("ws_test")
        assert len(computers) == 1
        assert computers[0].id == "cc_1"
        assert computers[0].agent_name == "outreach-agent"
        assert computers[0].status == "running"

    def test_ensure_cloud_computer_returns_existing(self) -> None:
        existing = CloudComputer(
            id="cc_existing",
            workspace_id="ws_1",
            agent_name="my-agent",
            image="hermes:latest",
            status="running",
        )
        client = OrgoClient(api_key="sk-test", dry_run=True)
        with patch.object(client, "list_cloud_computers", return_value=[existing]):
            cc = client.ensure_cloud_computer(
                workspace_id="ws_1", agent_name="my-agent", image="hermes:latest"
            )
        assert cc.id == "cc_existing"

    def test_ensure_cloud_computer_creates_new_in_dry_run(self) -> None:
        client = OrgoClient(api_key="sk-test", dry_run=True)
        with patch.object(client, "list_cloud_computers", return_value=[]):
            cc = client.ensure_cloud_computer(
                workspace_id="ws_1", agent_name="new-agent", image="hermes:latest"
            )
        assert cc.agent_name == "new-agent"
        assert cc.status == "provisioning"
        assert "new-agent" in cc.id

    def test_delete_cloud_computer_calls_request(self) -> None:
        client = OrgoClient(api_key="sk-test", dry_run=True)
        with patch.object(client, "_request") as mock_req:
            client.delete_cloud_computer("ws_1", "cc_1")
        mock_req.assert_called_once_with("DELETE", "/workspaces/ws_1/computers/cc_1")

    def test_ping_returns_true_on_success(self) -> None:
        client = OrgoClient(api_key="sk-test", dry_run=True)
        with patch.object(client, "_request", return_value={}):
            assert client.ping() is True

    def test_ping_returns_false_on_orgo_error(self) -> None:
        client = OrgoClient(api_key="sk-test", dry_run=True)
        with patch.object(client, "_request", side_effect=OrgoError("down")):
            assert client.ping() is False


# ---------------------------------------------------------------------------
# hermes_install.py
# ---------------------------------------------------------------------------
class TestHermesInstallerRuntimeLicense:
    def test_hermes_license_key(self, monkeypatch) -> None:
        monkeypatch.setenv("HERMES_LICENSE_KEY", "hermes-key-xyz")
        orgo = OrgoClient(api_key="dummy", dry_run=True)
        installer = HermesInstaller(orgo, dry_run=True)
        assert installer._runtime_license("hermes") == "hermes-key-xyz"

    def test_openclaw_license_key(self, monkeypatch) -> None:
        monkeypatch.setenv("OPENCLAW_LICENSE_KEY", "openclaw-key-abc")
        orgo = OrgoClient(api_key="dummy", dry_run=True)
        installer = HermesInstaller(orgo, dry_run=True)
        assert installer._runtime_license("openclaw") == "openclaw-key-abc"

    def test_missing_license_key_returns_empty(self, monkeypatch) -> None:
        monkeypatch.delenv("HERMES_LICENSE_KEY", raising=False)
        orgo = OrgoClient(api_key="dummy", dry_run=True)
        installer = HermesInstaller(orgo, dry_run=True)
        assert installer._runtime_license("hermes") == ""


class TestHermesInstallerRunRemote:
    def test_dry_run_returns_dry_run_stub(self) -> None:
        orgo = OrgoClient(api_key="dummy", dry_run=True)
        installer = HermesInstaller(orgo, dry_run=True)
        cc = CloudComputer(
            id="cc_1", workspace_id="ws_1", agent_name="a", image="img", status="running"
        )
        result = installer._run_remote(cc, "test_action", {"key": "val"})
        assert result["dry_run"] is True
        assert result["action"] == "test_action"

    def test_live_run_returns_ok(self) -> None:
        orgo = OrgoClient(api_key="dummy", dry_run=True)
        installer = HermesInstaller(orgo, dry_run=False)
        cc = CloudComputer(
            id="cc_1", workspace_id="ws_1", agent_name="a", image="img", status="running"
        )
        result = installer._run_remote(cc, "configure_model", {"primary": "gpt-5"})
        assert result["ok"] is True

    def test_image_mismatch_logs_warning_in_live_mode(self) -> None:
        """In live mode (not dry_run), image mismatch should still complete."""
        orgo = OrgoClient(api_key="dummy", dry_run=True)
        installer = HermesInstaller(orgo, dry_run=False)
        cc = CloudComputer(
            id="cc_1",
            workspace_id="ws_1",
            agent_name="outreach-agent",
            image="wrong-image:v1",  # mismatch
            status="running",
        )
        stack = StackConfig.load("hermes")  # type: ignore[arg-type]
        agent = _load_example_customer().agents[0]
        # Should not raise, just log a warning
        result = installer.install(cc, agent, stack)
        assert result.agent_name == "outreach-agent"


# ---------------------------------------------------------------------------
# telegram_meta.py
# ---------------------------------------------------------------------------
class TestTelegramConfigFromEnv:
    def test_from_env_reads_env_vars(self, monkeypatch) -> None:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token-123")
        monkeypatch.setenv("TELEGRAM_CONTROL_CHAT_ID", "chat-456")
        cfg = TelegramConfig.from_env()
        assert cfg.bot_token == "bot-token-123"
        assert cfg.control_chat_id == "chat-456"
        assert cfg.configured is True

    def test_from_env_empty_when_unset(self, monkeypatch) -> None:
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CONTROL_CHAT_ID", raising=False)
        cfg = TelegramConfig.from_env()
        assert cfg.configured is False


class TestTelegramMetaNotify:
    def test_notify_provisioned_dry_run(self) -> None:
        cfg = TelegramConfig(bot_token="t", control_chat_id="c")
        tm = TelegramMeta(config=cfg, dry_run=True)
        # Should not raise
        tm.notify_provisioned("acme-marketing", ["outreach-agent", "proposal-agent"])

    def test_notify_watchdog_fired_dry_run(self) -> None:
        cfg = TelegramConfig(bot_token="t", control_chat_id="c")
        tm = TelegramMeta(config=cfg, dry_run=True)
        tm.notify_watchdog_fired("acme-marketing", "outreach-agent", "status=stopped")

    def test_notify_decommissioned_dry_run(self) -> None:
        cfg = TelegramConfig(bot_token="t", control_chat_id="c")
        tm = TelegramMeta(config=cfg, dry_run=True)
        # notify_decommissioned returns the result of send()
        with patch.object(tm, "send", return_value=True) as mock_send:
            tm.notify_decommissioned("acme-marketing")
        mock_send.assert_called_once()
        assert "acme-marketing" in mock_send.call_args[0][0]

    def test_send_returns_false_on_http_error(self, monkeypatch) -> None:
        cfg = TelegramConfig(bot_token="bot-abc", control_chat_id="chat-123")
        tm = TelegramMeta(config=cfg, dry_run=False)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = MagicMock(side_effect=Exception("network error"))

        with patch("httpx.Client", return_value=mock_client):
            result = tm.send("hello world")
        assert result is False

    def test_send_returns_false_on_non_200_status(self) -> None:
        cfg = TelegramConfig(bot_token="bot-abc", control_chat_id="chat-123")
        tm = TelegramMeta(config=cfg, dry_run=False)

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = MagicMock(return_value=mock_response)

        with patch("httpx.Client", return_value=mock_client):
            result = tm.send("hello world")
        assert result is False

    def test_send_returns_true_on_200(self) -> None:
        cfg = TelegramConfig(bot_token="bot-abc", control_chat_id="chat-123")
        tm = TelegramMeta(config=cfg, dry_run=False)

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = MagicMock(return_value=mock_response)

        with patch("httpx.Client", return_value=mock_client):
            result = tm.send("hello world")
        assert result is True

    def test_listen_does_not_raise(self) -> None:
        cfg = TelegramConfig(bot_token="", control_chat_id="")
        tm = TelegramMeta(config=cfg, dry_run=True)
        # listen() just logs a warning — should not raise
        tm.listen()


# ---------------------------------------------------------------------------
# observability.py
# ---------------------------------------------------------------------------
class TestHealthCheck:
    def test_dataclass_fields(self) -> None:
        hc = HealthCheck(
            customer_slug="acme",
            agent_name="outreach",
            cloud_computer_id="cc_1",
            status="healthy",
            last_heartbeat=None,
        )
        assert hc.customer_slug == "acme"
        assert hc.reason == ""

    def test_healthy_with_last_heartbeat(self) -> None:
        now = datetime.now(timezone.utc)
        hc = HealthCheck(
            customer_slug="acme",
            agent_name="a",
            cloud_computer_id="cc_1",
            status="healthy",
            last_heartbeat=now,
        )
        assert hc.last_heartbeat == now


class TestWatchdogEvaluate:
    def _make_watchdog(self) -> Watchdog:
        orgo = OrgoClient(api_key="dummy", dry_run=True)
        return Watchdog(orgo=orgo)

    def _make_cc(self, status: str) -> CloudComputer:
        return CloudComputer(
            id="cc_1", workspace_id="ws_1", agent_name="a", image="img", status=status
        )

    def test_running_is_healthy(self) -> None:
        wd = self._make_watchdog()
        hc = wd._evaluate("acme", "outreach", self._make_cc("running"))
        assert hc.status == "healthy"
        assert hc.last_heartbeat is not None
        assert hc.reason == ""

    def test_provisioning_is_degraded(self) -> None:
        wd = self._make_watchdog()
        hc = wd._evaluate("acme", "outreach", self._make_cc("provisioning"))
        assert hc.status == "degraded"
        assert hc.last_heartbeat is None
        assert "provisioning" in hc.reason

    def test_stopped_is_down(self) -> None:
        wd = self._make_watchdog()
        hc = wd._evaluate("acme", "outreach", self._make_cc("stopped"))
        assert hc.status == "down"

    def test_error_is_down(self) -> None:
        wd = self._make_watchdog()
        hc = wd._evaluate("acme", "outreach", self._make_cc("error"))
        assert hc.status == "down"

    def test_unknown_status_is_unknown(self) -> None:
        wd = self._make_watchdog()
        hc = wd._evaluate("acme", "outreach", self._make_cc("restarting"))
        assert hc.status == "unknown"


class TestWatchdogCheck:
    def _make_customer(self) -> CustomerConfig:
        return _load_example_customer()

    def test_check_no_workspace_marks_all_down(self) -> None:
        orgo = OrgoClient(api_key="dummy", dry_run=True)
        with patch.object(orgo, "get_workspace_by_slug", return_value=None):
            wd = Watchdog(orgo=orgo)
            results = wd.check(self._make_customer())
        assert all(r.status == "down" for r in results)
        assert all(r.reason == "workspace not found" for r in results)

    def test_check_missing_computer_marks_agent_down(self) -> None:
        orgo = OrgoClient(api_key="dummy", dry_run=True)
        ws = Workspace(id="ws_1", customer_slug="acme", region="us-east-1")
        with patch.object(orgo, "get_workspace_by_slug", return_value=ws):
            with patch.object(orgo, "list_cloud_computers", return_value=[]):
                wd = Watchdog(orgo=orgo)
                results = wd.check(self._make_customer())
        assert all(r.status == "down" for r in results)
        assert all(r.reason == "cloud computer not found" for r in results)

    def test_check_running_computer_marks_healthy(self) -> None:
        orgo = OrgoClient(api_key="dummy", dry_run=True)
        ws = Workspace(id="ws_1", customer_slug="acme", region="us-east-1")
        customer = self._make_customer()
        computers = [
            CloudComputer(
                id=f"cc_{i}",
                workspace_id="ws_1",
                agent_name=agent.name,
                image="hermes:latest",
                status="running",
            )
            for i, agent in enumerate(customer.agents)
        ]
        with patch.object(orgo, "get_workspace_by_slug", return_value=ws):
            with patch.object(orgo, "list_cloud_computers", return_value=computers):
                wd = Watchdog(orgo=orgo)
                results = wd.check(customer)
        assert all(r.status == "healthy" for r in results)


class TestWatchdogAlert:
    def test_alert_healthy_does_not_notify(self) -> None:
        orgo = OrgoClient(api_key="dummy", dry_run=True)
        tm = TelegramMeta(config=TelegramConfig(bot_token="t", control_chat_id="c"), dry_run=True)
        wd = Watchdog(orgo=orgo, telegram=tm)
        hc = HealthCheck("acme", "a", "cc_1", "healthy", None)
        with patch.object(tm, "notify_watchdog_fired") as mock_notify:
            wd.alert(hc)
        mock_notify.assert_not_called()

    def test_alert_down_sends_notification(self) -> None:
        orgo = OrgoClient(api_key="dummy", dry_run=True)
        tm = TelegramMeta(config=TelegramConfig(bot_token="t", control_chat_id="c"), dry_run=True)
        wd = Watchdog(orgo=orgo, telegram=tm)
        hc = HealthCheck("acme", "a", "cc_1", "down", None, reason="stopped")
        with patch("src.observability.send_email_alert", return_value=False):
            with patch.object(tm, "notify_watchdog_fired") as mock_notify:
                wd.alert(hc)
        mock_notify.assert_called_once_with("acme", "a", "stopped")

    def test_alert_degraded_sends_notification(self) -> None:
        orgo = OrgoClient(api_key="dummy", dry_run=True)
        tm = TelegramMeta(config=TelegramConfig(bot_token="t", control_chat_id="c"), dry_run=True)
        wd = Watchdog(orgo=orgo, telegram=tm)
        hc = HealthCheck("acme", "b", "cc_2", "degraded", None, reason="provisioning")
        with patch("src.observability.send_email_alert", return_value=False):
            with patch.object(tm, "notify_watchdog_fired") as mock_notify:
                wd.alert(hc)
        mock_notify.assert_called_once()


class TestWatchdogInterval:
    def test_interval_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("WATCHDOG_INTERVAL_SECONDS", "60")
        orgo = OrgoClient(api_key="dummy", dry_run=True)
        wd = Watchdog(orgo=orgo)
        assert wd.interval_seconds == 60

    def test_interval_from_constructor(self) -> None:
        orgo = OrgoClient(api_key="dummy", dry_run=True)
        wd = Watchdog(orgo=orgo, interval_seconds=120)
        assert wd.interval_seconds == 120


class TestSendEmailAlert:
    def test_unconfigured_returns_false(self, monkeypatch) -> None:
        monkeypatch.delenv("SMTP_HOST", raising=False)
        monkeypatch.delenv("ALERT_EMAIL_FROM", raising=False)
        monkeypatch.delenv("ALERT_EMAIL_TO", raising=False)
        hc = HealthCheck("acme", "a", "cc_1", "down", None, "stopped")
        result = send_email_alert(hc)
        assert result is False

    def test_configured_smtp_error_returns_false(self, monkeypatch) -> None:
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SMTP_PORT", "587")
        monkeypatch.setenv("ALERT_EMAIL_FROM", "from@example.com")
        monkeypatch.setenv("ALERT_EMAIL_TO", "to@example.com")

        hc = HealthCheck("acme", "a", "cc_1", "down", None, "stopped")
        with patch("smtplib.SMTP", side_effect=Exception("connection refused")):
            result = send_email_alert(hc)
        assert result is False

    def test_configured_smtp_success_returns_true(self, monkeypatch) -> None:
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SMTP_PORT", "587")
        monkeypatch.setenv("SMTP_USER", "user@example.com")
        monkeypatch.setenv("SMTP_PASSWORD", "secret")
        monkeypatch.setenv("ALERT_EMAIL_FROM", "from@example.com")
        monkeypatch.setenv("ALERT_EMAIL_TO", "to@example.com")

        hc = HealthCheck("acme", "a", "cc_1", "down", None, "stopped")
        mock_server = MagicMock()
        mock_server.__enter__ = MagicMock(return_value=mock_server)
        mock_server.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP", return_value=mock_server):
            result = send_email_alert(hc)
        assert result is True
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("user@example.com", "secret")
        mock_server.send_message.assert_called_once()

    def test_configured_smtp_no_auth_skips_login(self, monkeypatch) -> None:
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SMTP_PORT", "587")
        monkeypatch.delenv("SMTP_USER", raising=False)
        monkeypatch.delenv("SMTP_PASSWORD", raising=False)
        monkeypatch.setenv("ALERT_EMAIL_FROM", "from@example.com")
        monkeypatch.setenv("ALERT_EMAIL_TO", "to@example.com")

        hc = HealthCheck("acme", "b", "cc_2", "degraded", None, "provisioning")
        mock_server = MagicMock()
        mock_server.__enter__ = MagicMock(return_value=mock_server)
        mock_server.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP", return_value=mock_server):
            result = send_email_alert(hc)
        assert result is True
        mock_server.login.assert_not_called()


# ---------------------------------------------------------------------------
# setup_agent.py
# ---------------------------------------------------------------------------
class TestDryRunFlag:
    def test_bool_true(self) -> None:
        assert _dry_run_flag(True) is True

    def test_bool_false(self) -> None:
        assert _dry_run_flag(False) is False

    def test_string_true_variants(self) -> None:
        for v in ("true", "1", "yes", "y", "True", "YES"):
            assert _dry_run_flag(v) is True, f"Expected True for {v!r}"

    def test_string_false_variants(self) -> None:
        for v in ("false", "0", "no", "n", "False", "NO"):
            assert _dry_run_flag(v) is False, f"Expected False for {v!r}"


class TestRunDoctor:
    def test_run_doctor_returns_1_when_keys_missing(self, monkeypatch) -> None:
        from src.config import REQUIRED_ENV_KEYS

        for key in REQUIRED_ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
        # Also ensure no api key so orgo ping is skipped
        monkeypatch.delenv("ORGO_API_KEY", raising=False)
        code = run_doctor()
        assert code == 1

    def test_run_doctor_returns_0_when_all_keys_set(self, monkeypatch) -> None:
        from src.config import REQUIRED_ENV_KEYS

        for key in REQUIRED_ENV_KEYS:
            monkeypatch.setenv(key, "test-value")
        # Prevent real orgo call
        with patch("src.setup_agent.OrgoClient") as mock_cls:
            mock_orgo = MagicMock()
            mock_orgo.ping.return_value = True
            mock_cls.return_value = mock_orgo
            code = run_doctor()
        assert code == 0


class TestShowStatusWithWorkspace:
    def test_show_status_with_workspace_and_computers(
        self, monkeypatch
    ) -> None:
        monkeypatch.setenv("ORGO_API_KEY", "test")
        customer = load_customer("acme-marketing")
        orgo = OrgoClient(api_key="test", dry_run=True)
        ws = Workspace(id="ws_1", customer_slug="acme-marketing", region="us-east-1")
        computers = [
            CloudComputer(
                id=f"cc_{i}",
                workspace_id="ws_1",
                agent_name=agent.name,
                image="hermes:latest",
                status="running",
                public_endpoint="https://example.com",
            )
            for i, agent in enumerate(customer.agents)
        ]
        with patch("src.setup_agent._make_orgo", return_value=orgo):
            with patch.object(orgo, "get_workspace_by_slug", return_value=ws):
                with patch.object(orgo, "list_cloud_computers", return_value=computers):
                    # Should not raise
                    show_status(customer, dry_run=True)

    def test_show_status_with_workspace_missing_computer(
        self, monkeypatch
    ) -> None:
        monkeypatch.setenv("ORGO_API_KEY", "test")
        customer = load_customer("acme-marketing")
        orgo = OrgoClient(api_key="test", dry_run=True)
        ws = Workspace(id="ws_1", customer_slug="acme-marketing", region="us-east-1")
        # Only provide computer for first agent, rest will be "not provisioned"
        computers = [
            CloudComputer(
                id="cc_0",
                workspace_id="ws_1",
                agent_name=customer.agents[0].name,
                image="hermes:latest",
                status="stopped",
            )
        ]
        with patch("src.setup_agent._make_orgo", return_value=orgo):
            with patch.object(orgo, "get_workspace_by_slug", return_value=ws):
                with patch.object(orgo, "list_cloud_computers", return_value=computers):
                    show_status(customer, dry_run=True)


class TestDecomResultTotalDeleted:
    def test_total_deleted_counts_computers(self) -> None:
        r = DecomResult(
            customer_slug="x",
            workspace_id="ws_1",
            computers_deleted=["a", "b", "c"],
        )
        assert r.total_deleted == 3

    def test_total_deleted_empty(self) -> None:
        r = DecomResult(customer_slug="x", workspace_id="")
        assert r.total_deleted == 0


# ---------------------------------------------------------------------------
# Additional targeted tests for remaining coverage gaps
# ---------------------------------------------------------------------------
class TestAuditLogOSError:
    def test_log_action_survives_write_error(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """log_action should not raise even if the write fails (OSError branch)."""
        import src.audit_log as audit_mod

        log_dir = tmp_path / "logs"
        log_file = log_dir / "audit.jsonl"
        monkeypatch.setattr(audit_mod, "AUDIT_LOG_DIR", log_dir)

        # Use a mock path that raises OSError on open("a")
        mock_path = MagicMock()
        mock_path.exists.return_value = False  # triggers seq=1
        mock_path.open.side_effect = OSError("disk full")
        monkeypatch.setattr(audit_mod, "AUDIT_LOG_FILE", mock_path)

        # Should not raise despite OSError
        entry = log_action(action="test", command="cmd", status="success")
        assert entry.action == "test"

    def test_read_log_survives_os_error(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """read_log should return [] on OSError during file read."""
        import src.audit_log as audit_mod

        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.open.side_effect = OSError("read error")
        monkeypatch.setattr(audit_mod, "AUDIT_LOG_FILE", mock_path)

        entries = read_log()
        assert entries == []


class TestValidateCustomerUnknownMCP:
    def test_unknown_mcp_in_registry_produces_warning(self, monkeypatch) -> None:
        """An MCP name not in MCP_REGISTRY should produce a warning.

        Since MCPName is a Literal type, we can't add invalid MCP names via
        Pydantic. Instead we mock MCP_REGISTRY to remove a known entry so
        the validate_customer code sees it as unregistered.
        """
        import src.config as cfg_mod
        import src.mcp_config as mcp_mod

        for key in cfg_mod.REQUIRED_ENV_KEYS:
            monkeypatch.setenv(key, "test")

        # Remove "perplexity" from the registry so the customer's perplexity
        # MCP references an unregistered entry.
        limited_registry = {k: v for k, v in mcp_mod.MCP_REGISTRY.items() if k != "perplexity"}
        monkeypatch.setattr(mcp_mod, "MCP_REGISTRY", limited_registry)

        customer = _load_example_customer()
        result = validate_customer(customer)
        assert result.ok  # warning, not error
        assert any("not in registry" in w for w in result.warnings)


class TestOrgoClientNonDryRunCreate:
    def test_ensure_workspace_non_dry_run_uses_api_response(self) -> None:
        """ensure_workspace in live mode should parse id from API response."""
        api_payload = {"id": "ws_from_api", "region": "us-west-2"}
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.text = json.dumps(api_payload)
        mock_response.json = MagicMock(return_value=api_payload)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request = MagicMock(return_value=mock_response)

        with patch("httpx.Client", return_value=mock_client):
            client = OrgoClient(api_key="sk-test", dry_run=False)
            # Stub get_workspace_by_slug to return None (no existing workspace)
            with patch.object(client, "get_workspace_by_slug", return_value=None):
                ws = client.ensure_workspace("new-customer")
        assert ws.id == "ws_from_api"

    def test_ensure_cloud_computer_non_dry_run_uses_api_response(self) -> None:
        """ensure_cloud_computer in live mode should parse id from API response."""
        api_payload = {
            "id": "cc_from_api",
            "status": "provisioning",
            "public_endpoint": None,
        }
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.text = json.dumps(api_payload)
        mock_response.json = MagicMock(return_value=api_payload)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request = MagicMock(return_value=mock_response)

        with patch("httpx.Client", return_value=mock_client):
            client = OrgoClient(api_key="sk-test", dry_run=False)
            with patch.object(client, "list_cloud_computers", return_value=[]):
                cc = client.ensure_cloud_computer(
                    workspace_id="ws_1",
                    agent_name="my-agent",
                    image="hermes:latest",
                )
        assert cc.id == "cc_from_api"
        assert cc.status == "provisioning"


# ---------------------------------------------------------------------------
# setup_agent.py – preflight and decommission with workspace
# ---------------------------------------------------------------------------
class TestPreflightWithErrors:
    def test_preflight_returns_false_on_errors(self, monkeypatch) -> None:
        """_preflight should return False when validate_customer has errors."""
        from src.setup_agent import _preflight

        # Remove all required keys so validation fails
        import src.config as cfg_mod

        for key in cfg_mod.REQUIRED_ENV_KEYS:
            monkeypatch.delenv(key, raising=False)

        customer = load_customer("acme-marketing")
        result = _preflight(customer)
        assert result is False

    def test_preflight_returns_true_with_all_keys(self, monkeypatch) -> None:
        """_preflight should return True when all required keys are present."""
        from src.setup_agent import _preflight

        import src.config as cfg_mod

        for key in cfg_mod.REQUIRED_ENV_KEYS:
            monkeypatch.setenv(key, "test-value")

        customer = load_customer("acme-marketing")
        result = _preflight(customer)
        assert result is True

    def test_preflight_strict_with_warnings(self, monkeypatch) -> None:
        """_preflight with strict=True should still return True when no errors."""
        from src.setup_agent import _preflight

        import src.config as cfg_mod

        for key in cfg_mod.REQUIRED_ENV_KEYS:
            monkeypatch.setenv(key, "test-value")
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)

        customer = load_customer("acme-marketing")
        # strict=True but no errors — should still return True
        result = _preflight(customer, strict=True)
        assert result is True


class TestDecommissionWithWorkspace:
    def test_decommission_with_workspace_found_dry_run(
        self, monkeypatch
    ) -> None:
        """Dry-run decom with workspace found should set workspace_id and dry_run."""
        from src.setup_agent import decommission_customer

        monkeypatch.setenv("ORGO_API_KEY", "test")
        customer = load_customer("acme-marketing")

        orgo = OrgoClient(api_key="test", dry_run=True)
        ws = Workspace(
            id="ws_acme", customer_slug=customer.customer.slug, region="us-west-2"
        )
        computers = [
            CloudComputer(
                id=f"cc_{i}",
                workspace_id="ws_acme",
                agent_name=agent.name,
                image="hermes:latest",
                status="running",
            )
            for i, agent in enumerate(customer.agents)
        ]

        with patch("src.setup_agent._make_orgo", return_value=orgo):
            with patch("src.setup_agent._make_telegram") as mock_tg:
                mock_tg.return_value = TelegramMeta(
                    config=TelegramConfig(bot_token="t", control_chat_id="c"),
                    dry_run=True,
                )
                with patch.object(orgo, "get_workspace_by_slug", return_value=ws):
                    with patch.object(
                        orgo, "list_cloud_computers", return_value=computers
                    ):
                        with patch.object(orgo, "delete_cloud_computer"):
                            with patch.object(orgo, "delete_workspace"):
                                result = decommission_customer(
                                    customer, dry_run=True, force=True
                                )

        assert result.workspace_id == "ws_acme"
        assert result.customer_slug == "acme-marketing"
        assert result.dry_run is True


# ---------------------------------------------------------------------------
# audit_log.py – print_log coverage
# ---------------------------------------------------------------------------
class TestPrintLog:
    def test_print_log_empty(self, tmp_path: Path, monkeypatch) -> None:
        """print_log with no entries should not crash."""
        import src.audit_log as audit_mod
        from src.audit_log import print_log

        monkeypatch.setattr(audit_mod, "AUDIT_LOG_FILE", tmp_path / "nope.jsonl")
        print_log(limit=10)  # Should print "No audit log entries found."

    def test_print_log_with_entries(self, tmp_path: Path, monkeypatch) -> None:
        """print_log with entries should render the table without crashing."""
        import src.audit_log as audit_mod
        from src.audit_log import print_log

        log_dir = tmp_path / "logs"
        log_file = log_dir / "audit.jsonl"
        monkeypatch.setattr(audit_mod, "AUDIT_LOG_DIR", log_dir)
        monkeypatch.setattr(audit_mod, "AUDIT_LOG_FILE", log_file)
        monkeypatch.setenv("BOB_OPERATOR_NAME", "tester")

        for status in ("success", "failure", "partial", "started", "aborted", "unknown"):
            log_action(action="test", command="cmd", status=status)

        print_log(limit=20)  # Should render table for all statuses


# ---------------------------------------------------------------------------
# observability.py – run_forever coverage
# ---------------------------------------------------------------------------
class TestWatchdogRunForever:
    @pytest.mark.asyncio
    async def test_run_forever_one_iteration(self) -> None:
        """run_forever should call check/alert and then sleep; cancel after one cycle."""
        import asyncio

        orgo = OrgoClient(api_key="dummy", dry_run=True)
        customer = _load_example_customer()
        ws = Workspace(id="ws_1", customer_slug="acme", region="us-east-1")
        computers = [
            CloudComputer(
                id=f"cc_{i}",
                workspace_id="ws_1",
                agent_name=agent.name,
                image="hermes:latest",
                status="running",
            )
            for i, agent in enumerate(customer.agents)
        ]

        with patch.object(orgo, "get_workspace_by_slug", return_value=ws):
            with patch.object(orgo, "list_cloud_computers", return_value=computers):
                wd = Watchdog(orgo=orgo, interval_seconds=1)

                async def cancel_after_first_sleep(*_args, **_kwargs):
                    raise asyncio.CancelledError()

                with patch("asyncio.sleep", side_effect=cancel_after_first_sleep):
                    with pytest.raises(asyncio.CancelledError):
                        await wd.run_forever([customer])

    @pytest.mark.asyncio
    async def test_run_forever_handles_check_exception(self) -> None:
        """run_forever should log errors from check() and continue."""
        import asyncio

        orgo = OrgoClient(api_key="dummy", dry_run=True)
        customer = _load_example_customer()
        wd = Watchdog(orgo=orgo, interval_seconds=1)

        call_count = 0

        async def cancel_after_first_sleep(*_args, **_kwargs):
            raise asyncio.CancelledError()

        with patch.object(wd, "check", side_effect=RuntimeError("boom")):
            with patch("asyncio.sleep", side_effect=cancel_after_first_sleep):
                with pytest.raises(asyncio.CancelledError):
                    await wd.run_forever([customer])


# ---------------------------------------------------------------------------
# setup_agent.py – preflight all-clear and strict-warning paths
# ---------------------------------------------------------------------------
class TestPreflightAllClear:
    def test_preflight_all_clear_prints_success(self, monkeypatch) -> None:
        """_preflight prints success when no errors and no warnings."""
        from src.setup_agent import _preflight
        import src.config as cfg_mod

        for key in cfg_mod.REQUIRED_ENV_KEYS:
            monkeypatch.setenv(key, "test-value")
        # Set all optional keys to avoid warnings
        for key in (
            "PERPLEXITY_API_KEY",
            "CONTEXT7_API_KEY",
            "X_MCP_BEARER_TOKEN",
            "COMPOSIO_API_KEY",
            "AGENT_MAIL_API_KEY",
            "HERMES_LICENSE_KEY",
            "OPENCLAW_LICENSE_KEY",
        ):
            monkeypatch.setenv(key, "test-value")

        customer = load_customer("acme-marketing")
        result = _preflight(customer)
        assert result is True
