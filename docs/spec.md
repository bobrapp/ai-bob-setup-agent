# ai-bob-setup-agent — Product Spec

Distilled from "The $1M+ Solo AI Agent Business (Full Course)" — Greg Isenberg with Nick Vasilescu of Orgo (2026-05-12).

## 1. Problem

Roughly 99% of legacy businesses are behind on AI. They want an "AI employee" but don't have the technical fluency to assemble the stack. Today, the only way to get a working Hermes-on-Orgo agent is to schedule a 15-minute call with Nick and have him set it up by hand. That doesn't scale.

A solo operator who can package and sell that setup as an offer can clear meaningful revenue — Nick puts OpenClaw agents at ~$5K/mo and Hermes agents at ~$10K/mo. But every onboarding is high-touch. The bottleneck is the setup ritual: create a customer workspace, spin up a cloud computer, install Hermes, wire up MCPs, set up watchdogs, ship.

## 2. Solution

**ai-bob-setup-agent** is an automated setup agent that performs the manual onboarding ritual end-to-end. A new customer signs up, ai-bob-setup-agent:

1. Provisions an Orgo workspace dedicated to the customer.
2. Spins up a fresh cloud computer per agent.
3. Installs and configures Hermes (or OpenClaw) on that machine.
4. Wires up the customer-specific MCPs (Perplexity for live research, Context7 for live docs, X MCP for social signals, Composio for app actions, Agent Mail for email).
5. Loads the customer's Obsidian-style second-brain workspace.
6. Stands up watchdogs and email-based observability.
7. Hands off a Telegram channel through which the customer (or the operator) talks to a meta-agent that manages all the per-customer agents.

The whole thing is one command from a fresh machine to a deployed state.

## 3. Target user

**Primary**: Solo AI operators / "agent-business" founders. AI-fluent, comfortable with the command line, building a $1M ARR services business by selling AI employees to legacy SMBs. They are Bob — they already understand what Hermes and Orgo are; they need leverage so they aren't the bottleneck.

**Secondary**: Their customers — marketing agencies, law firms, insurance agencies, manufacturers, wholesalers, real estate operators. The customers don't run ai-bob-setup-agent themselves; they receive a working agent without seeing the plumbing.

## 4. The offer (what Bob sells)

Per the video:
- **Unlimited agents, unlimited usage, unlimited monitoring, security, and ongoing changes.**
- **Price**: ~$5K/mo for OpenClaw-tier, ~$10K/mo for Hermes-tier.
- **No token-talk, no credit-talk** — the customer never sees a meter. That's how the magic survives the contract.
- **Reality**: customers think they need 10 to 100 agents, in practice 1 to 3 do the bulk of the work. Bob priced for the imagined need, delivered against the real need.

## 5. Target verticals (in priority order)

Avoid: healthcare, finance (too regulated for a solo operator).

Pursue:
1. Marketing agencies
2. Law firms
3. Insurance agencies
4. Manufacturers
5. Wholesalers
6. Real estate

"Diverge then converge" — try several, see which one pulls, then sub-niche by geography or professional sub-type (commercial real estate in Florida, matrimonial law, etc.).

## 6. The stack

**Customer-facing tools** (the surface area the customer touches):
- Granola (meeting notes)
- Trello (project state)
- Loom (async video)
- Superhuman (email)
- Asana (tasks)
- Telegram (the meta-agent control channel)

**Agent-building stack** (Bob's tools):
- Hermes (the headline agent runtime)
- OpenClaw (lighter-tier agent runtime)
- Orgo (the cloud-computer platform where agents run)
- Composio (app-action connectors)
- Agent Mail (email infrastructure for agents)
- Codex / Claude Code (Bob's coding agent for writing agent logic)
- Obsidian (second-brain layer per customer)

**MCPs** (model context protocol servers that give agents fresh context):
- Perplexity MCP (live web search)
- Context7 MCP (live docs)
- X MCP (live social signals)

**Models**:
- Default for tool calling: GPT 5.5
- Light/cheap workloads: GLM 5.1 (Z.AI), Kimmy
- Long-horizon coding tasks: Opus 4.7

## 7. Architecture

```
Bob (solopreneur)
  |
  +-- ai-bob-setup-agent (this project)
        |
        +-- Orgo control plane
              |
              +-- Workspace per customer
                    |
                    +-- Cloud computer per agent (1-3 typical)
                          |
                          +-- Hermes / OpenClaw runtime
                                |
                                +-- MCPs: Perplexity, Context7, X
                                +-- Composio + Agent Mail
                                +-- Obsidian second-brain (per customer)
                                +-- Watchdog + email observability
```

A Telegram-controlled meta-agent sits across the workspaces and can install Hermes, manage VMs, and patch problems on the fly. Nick's reference deployment manages 27 VMs from one Telegram channel.

## 8. Workflows ai-bob-setup-agent automates

1. **Onboard new customer** — Create Orgo workspace; provision N cloud computers; install Hermes; configure MCPs; load customer config; register with meta-agent; send credentials to customer.
2. **Add a new agent to an existing customer** — Provision cloud computer; install runtime; attach to customer workspace; register watchdog.
3. **Update a customer's stack** — Pull latest agent config; rebuild MCPs; restart runtime; verify health.
4. **Daily health check** — Walk all agents across all customers; verify reachability; collect logs; email a digest.
5. **Incident response** — When a watchdog fires, page Bob via Telegram; capture the failure; (later) auto-remediate common classes.
6. **Decommission a customer** — Tear down workspace; archive logs; revoke credentials.

## 9. Production requirements

- **One-command install** — `make install` on a fresh machine reaches a configured state.
- **Idempotent** — re-running the setup must converge, not duplicate.
- **Configuration as code** — every customer described in a YAML/TOML file checked into a private repo.
- **Secrets out of the repo** — `.env` and `.env.example` pattern; never commit credentials.
- **Observability** — every agent emits a structured heartbeat; missing heartbeats trigger Telegram + email alerts.
- **CI** — every push runs lint + dry-run setup against a fixture customer.
- **CD** — pushes to main auto-deploy the static site (docs + landing) to GitHub Pages.
- **Logging** — every action ai-bob-setup-agent takes logs to docs/build-log.md per the AIGovOps provenance rule, plus a structured operational log.

## 10. Success criteria

- A fresh customer is onboarded end-to-end in under 15 minutes of Bob's attention.
- The system manages 25+ customer agents without Bob touching individual VMs.
- A new vertical can be added by writing one config file plus optional prompt tweaks.
- Watchdog catches 100% of agent-down events before the customer notices.
- The repo is public, documented, and a stranger can read README + install.html and go from zero to first customer in one afternoon.

## 11. Out of scope (for v0.1)

- Auto-acquiring customers (sales pipeline).
- Auto-billing (Stripe/contracts).
- Self-serve customer signup (customers come through Bob's sales process).
- Healthcare and finance verticals.
- Replacing Bob's judgment on what to build for the customer — ai-bob-setup-agent installs the runtime, Bob still writes the customer-specific agent logic.

## 12. The closing-thoughts framing (t=2741s / 45:28)

This is where the user dropped the link. Nick's closing pitch: the solopreneur era is real, AI fluency is the rare skill, and the gap between "can stand up agents" and "can't" is widening fast. The opportunity window is measured in months. ai-bob-setup-agent is the operational lever that lets a single person actually serve the demand.
