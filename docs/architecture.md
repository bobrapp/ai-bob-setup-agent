# Architecture

How the pieces fit together.

## Topology

```
Bob (solopreneur, single human operator)
 │
 ├─ ai-bob-setup-agent (this repo)
 │   │
 │   ├─ CLI (src/setup_agent.py)
 │   │     onboard | add-agent | decommission | doctor | list
 │   │
 │   ├─ Operator scripts (scripts/)
 │   │     bootstrap, provision_workspace, provision_agent, healthcheck, watchdog
 │   │
 │   ├─ Telegram meta-agent (src/telegram_meta.py)
 │   │     outbound notifications + inbound command surface
 │   │
 │   └─ Observability (src/observability.py)
 │         watchdog loop, email alerts, structured logging
 │
 └─ Orgo control plane (external)
       │
       └─ Workspace per customer (one per customer slug)
             │
             └─ Cloud computer per agent (1–3 typical)
                   │
                   ├─ Hermes or OpenClaw runtime
                   ├─ MCPs: Perplexity · Context7 · X
                   ├─ Composio (app actions)
                   ├─ Agent Mail (email identity)
                   ├─ Obsidian second-brain layer (Hermes tier)
                   └─ Watchdog heartbeat
```

## Boundaries

| Concern | Lives in | Notes |
|--------|----------|-------|
| Customer config | `config/customers/<slug>.yaml` (gitignored) | One YAML per customer. Pydantic-validated. |
| Stack definition | `config/stacks/{hermes,openclaw}.yaml` | Loaded by tier. Models, MCPs, resources. |
| Operator credentials | `.env` (gitignored) | `python-dotenv`. Never logged. |
| Orgo HTTP surface | `src/orgo_client.py` | Thin wrapper. Idempotent ensure_* helpers. |
| Runtime install | `src/hermes_install.py` | Same code path for Hermes and OpenClaw — tier read from stack config. |
| MCP wiring | `src/mcp_config.py` | Registry-driven. Add a row to extend. |
| Telegram | `src/telegram_meta.py` | Outbound wired; inbound is a documented extension point. |
| Observability | `src/observability.py` | Watchdog + SMTP alerts. |
| Provenance | `docs/build-log.md` | Per the AIGovOps Foundation rule. |

## Data flow — onboard

1. Operator runs `make onboard CUSTOMER=acme-marketing`.
2. `setup_agent.cli` invokes `onboard_customer(customer, dry_run)`.
3. `OrgoClient.ensure_workspace(slug)` → existing or new workspace.
4. For each agent in the customer config:
   1. `StackConfig.load(tier)` reads the stack YAML.
   2. `OrgoClient.ensure_cloud_computer(workspace_id, agent_name, image, resources)` → cloud computer.
   3. `HermesInstaller.install(cloud_computer, agent, stack)`:
      - Bootstrap runtime
      - Install MCPs (`MCPInstaller.install` per MCP)
      - Install connectors
      - Load second-brain seed (if enabled)
      - Apply model config
      - Reload runtime
5. `TelegramMeta.notify_provisioned(slug, agent_names)`.
6. Structured logs emit at every step.

## Idempotency contract

Every `ensure_*` call must be safe to invoke repeatedly:

- `ensure_workspace(slug)` — looks up by slug; creates only if missing.
- `ensure_cloud_computer(workspace_id, agent_name, ...)` — looks up by name in the workspace; creates only if missing.
- `MCPInstaller.install(cc, name)` — install command is itself idempotent at the package-manager level.

This means a partial failure mid-onboard can be recovered by re-running the same command. No state-tracking files. No reconciliation logic. The platform is the source of truth.

## Dry-run mode

`dry_run=True` flows through the entire stack:

- `OrgoClient` — logs intended HTTP calls, returns stub objects with deterministic IDs (e.g. `ws_dry_<slug>`).
- `HermesInstaller` — logs remote actions but does not execute.
- `MCPInstaller` — logs intended install commands.
- `TelegramMeta` — logs the message body, returns success.

Net effect: CI can validate the orchestration path with zero credentials.

## Failure modes

| Failure | Detected by | Operator action |
|---------|-------------|-----------------|
| Orgo API 5xx | `OrgoError` raised; `onboard` exits non-zero | Retry. Idempotent so safe. |
| Hermes license expired | `bootstrap_runtime` returns error | Refresh license in `.env`, re-run. |
| MCP key missing | Warning logged at install time | Fill in `.env`, re-run. Agent runs without that MCP until then. |
| Telegram unreachable | Notify functions return `False` silently | Check token; non-blocking. |
| SMTP unreachable | Alert email returns `False` silently | Telegram alert still fires. Non-blocking. |
| Cloud computer dies | `Watchdog._evaluate` returns `down` | Telegram + email alerts. Manual intervention. |
| Watchdog itself dies | External — systemd / cron / monitoring | Restart the watchdog process. |

## Scaling envelope

Tested up to: dry-run onboarding of a 3-agent customer (in CI).

Designed for: 25+ cloud computers per operator across many customers (per Nick's reference deployment of 27 VMs).

Hard ceiling: not measured. Likely network and Telegram-channel ergonomics rather than the orchestration code.

## Extension points

- **New MCP** — add to `MCP_REGISTRY` in `src/mcp_config.py`, reference by name from customer YAML.
- **New connector** — add a row to `connectors:` in the stack YAML, handle in `HermesInstaller._run_remote("install_connector", ...)`.
- **New runtime tier** — add a stack YAML to `config/stacks/`, ensure `Tier` literal includes the new name in `src/config.py`.
- **New observability target** — implement an alert function in `src/observability.py` and call it from `Watchdog.alert`.
- **New CLI command** — add a `@cli.command` to `src/setup_agent.py`.
- **Inbound Telegram commands** — implement `TelegramMeta.listen` per the docstring sketch.
