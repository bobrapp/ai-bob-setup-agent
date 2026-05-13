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

## Complete Tool Stack

The system integrates 25+ tools across seven layers. Here's how they relate.

### Layer 1 — Cloud Infrastructure
| Tool | Role | Module | Status |
|------|------|--------|--------|
| **Orgo** | Cloud-computer platform: one workspace per customer, one VM per agent | `src/orgo_client.py` | Implemented (HTTP client + dry-run) |

### Layer 2 — Agent Runtimes
| Tool | Role | Tier | Module |
|------|------|------|--------|
| **Hermes** | Premium agent runtime with full tool-calling, second brain, all MCPs | $10K/mo | `src/hermes_install.py` |
| **OpenClaw** | Standard agent runtime, lighter resources, fewer MCPs by default | $5K/mo | `src/hermes_install.py` |

### Layer 3 — AI Models (primary → fallback → light)
| Model | Provider | Role | Used by |
|-------|----------|------|---------|
| **GPT 5.5** | OpenAI | Primary — default for all tool-calling | Both tiers |
| **Opus 4.7** | Anthropic | Fallback — long-horizon coding, complex multi-step reasoning | Hermes only |
| **GLM 5.1** | ZhipuAI | Light — cheap high-volume routine tasks | Both tiers |
| **Kimmy** | Kimi (Moonshot) | Light fallback — runner-up to GLM 5.1 | OpenClaw only |

The model tier pattern is explicit: every agent has a `primary` model for quality-critical calls,
and at least one `light` model for cost-sensitive volume work. Hermes adds a `fallback` for
complex tasks that benefit from Anthropic's reasoning.

### Layer 4 — MCPs (Model Context Protocol Servers)
| MCP | Purpose | Package | Required by |
|-----|---------|---------|-------------|
| **Perplexity** | Live web search — facts the model wasn't trained on | `@modelcontextprotocol/server-perplexity` | Both tiers |
| **Context7** | Live documentation — up-to-date API/tool setup context | `@upstash/context7-mcp` | Hermes required, OpenClaw optional |
| **X MCP** | Live social signals — Twitter/X posts and trends | `x-mcp-server` | Optional |
| **Orgo MCP** | Agent self-management — agents can control their own cloud computers | `@nickvasilescu/orgo-mcp` | Optional |

MCPs give the agent live context beyond its training cutoff. Per Nick: "I've given Claude Code
Perplexity as a tool via MCP... it just sort of did it." The agent resolves ambiguity by
searching live docs (Context7) and live web (Perplexity) before acting.

### Layer 5 — Connectors
| Connector | Purpose | Sub-apps (via Composio) | Module |
|-----------|---------|------------------------|--------|
| **Composio** | App-action hub — connects the agent to business tools | Gmail, Google Calendar, Notion, Trello, Asana, Superhuman, Granola, Slack, HubSpot, Salesforce | `src/hermes_install.py` → `_run_remote("install_connector")` |
| **Agent Mail** | Email infrastructure — agent-specific email identities | — | `src/hermes_install.py` → `_run_remote("install_connector")` |

Composio is the multiplier: a single connector install gives access to hundreds of app integrations.
The customer YAML specifies which Composio apps each agent can use (e.g., `composio_apps: [gmail, trello, notion]`).

### Layer 6 — Second Brain
| Tool | Purpose | Tier | Module |
|------|---------|------|--------|
| **Obsidian** | Markdown-on-disk knowledge vault — per-customer durable memory | Hermes only | `src/hermes_install.py` → `_run_remote("load_second_brain")` |

Per the video: agents reference an Obsidian vault from their `agents.mmd` context file.
The `.mmd` file tells the agent *who* the customer is and *where* to find context.
As the agent works, it writes discoveries back to the vault, building institutional memory.

### Layer 7 — Operator & Monitoring
| Tool | Purpose | Module | Status |
|------|---------|--------|--------|
| **Telegram** | Meta-agent control channel — notifications + inbound commands | `src/telegram_meta.py` | Outbound implemented; inbound documented |
| **Email/SMTP** | Alert delivery for watchdog-fired events | `src/observability.py` | Implemented |
| **Watchdog** | Heartbeat monitoring — catches failures before customers notice | `src/observability.py` | Implemented |

### Operator-Side Tools (not provisioned, used to build/manage)
| Tool | Purpose | Notes |
|------|---------|-------|
| **Claude Code** | AI coding agent — used to build and configure agents | Operator's primary tool; connects MCPs for live context |
| **Codex** | OpenAI's coding agent — alternative to Claude Code | Per video: "pair Claude Code or Codex with MCPs" |

### Customer-Facing Surface (what the end customer touches)
| Surface | Purpose | Config key |
|---------|---------|-----------|
| **Telegram channel** | Direct communication with their agent(s) | `surface.telegram_channel` |
| **Weekly Loom digest** | Async video summary of agent work | `surface.weekly_loom_digest` |
| **Trello board** | Shared project board managed by agents | `surface.trello_board` |
| **Granola meeting notes** | AI meeting notes from discovery/check-in calls | `surface.granola_meeting_notes` |

## Context File Pattern (agents.mmd)

Per the video (28:14), each agent uses an `.mmd` (Markdown) context file that acts as
the agent's "briefing document." The file tells the agent:

1. **Who** — customer name, vertical, key contacts
2. **What** — the agent's specific role and responsibilities
3. **Where** — paths to the Obsidian vault, Composio app scopes, MCP configs
4. **How** — behavioral guidelines, escalation rules, output formats

```
# agents.mmd — outreach-agent context file
# Loaded into the agent's working memory at boot.

## Identity
You are outreach-agent for Acme Marketing LLC.
Your role: cold outbound + reply triage.

## Second Brain
Check your Obsidian vault at /data/obsidian/ for:
- Customer personas (personas/)
- Previous outreach templates (templates/)
- Meeting notes from Granola (meetings/)

## Tools
- Gmail via Composio for sending/receiving
- Trello via Composio for lead tracking
- Perplexity MCP for prospect research
- Context7 MCP for API documentation

## Escalation
If confidence < 70% on any reply, draft but do not send.
Flag for human review via Telegram.
```

This pattern is what makes Obsidian the "second brain layer" — the agent reads and writes
to a persistent Markdown vault that accumulates knowledge over time.

## Tool Relationship Map

```
Operator (Bob)
│
├─ Claude Code / Codex ─── operator coding tools
│   └─ connected via MCPs to ───┐
│                                │
│  ┌─────────────────────────────┘
│  ↓
│  Perplexity MCP ─── live search
│  Context7 MCP   ─── live docs
│  X MCP          ─── social signals
│  Orgo MCP       ─── cloud control
│
├─ Telegram ─── meta-agent control channel
│   └─ monitors all customer VMs
│
└─ Orgo (cloud platform)
    │
    └─ Workspace (per customer)
        │
        └─ Cloud Computer (per agent)
            │
            ├─ Runtime: Hermes or OpenClaw
            │   └─ Models: GPT 5.5 (primary)
            │              Opus 4.7 (fallback, Hermes only)
            │              GLM 5.1 / Kimmy (light)
            │
            ├─ MCPs: Perplexity · Context7 · X · Orgo
            │
            ├─ Composio hub ─── app actions
            │   ├─ Gmail
            │   ├─ Google Calendar
            │   ├─ Notion
            │   ├─ Trello / Asana
            │   ├─ Superhuman
            │   ├─ Granola
            │   ├─ Slack
            │   └─ HubSpot / Salesforce
            │
            ├─ Agent Mail ─── email identity
            │
            ├─ Obsidian vault ─── second brain (Hermes)
            │   └─ context file (agents.mmd)
            │
            └─ Watchdog heartbeat ─── health monitoring
                └─ alerts via Telegram + Email
```
