# ai-bob-setup-agent

[![CI](https://github.com/bobrapp/ai-bob-setup-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/bobrapp/ai-bob-setup-agent/actions/workflows/ci.yml)
[![GitHub Pages](https://github.com/bobrapp/ai-bob-setup-agent/actions/workflows/deploy-pages.yml/badge.svg)](https://github.com/bobrapp/ai-bob-setup-agent/actions/workflows/deploy-pages.yml)

> Automated setup agent for the $1M+ solo AI agent business.
> Provisions Orgo workspaces and Hermes / OpenClaw agents end-to-end so one
> operator can serve many customers without becoming the bottleneck.

**Live site:** https://bobrapp.github.io/ai-bob-setup-agent
**Source video:** [The $1M+ Solo AI Agent Business (Full Course)](https://www.youtube.com/watch?v=BI-MNjm1tTQ) — Greg Isenberg with Nick Vasilescu (Orgo)

---

## What this is

Roughly 99% of legacy businesses are behind on AI. They want an "AI employee"
but cannot assemble the stack themselves. Today the only way to get a working
Hermes-on-Orgo agent is to book a 15-minute call with Nick and have him set it
up by hand. That does not scale.

`ai-bob-setup-agent` performs that manual ritual automatically. One command
takes a fresh customer config and turns it into:

1. A dedicated Orgo workspace.
2. N cloud computers, one per agent.
3. Hermes (or OpenClaw) installed and configured on each.
4. MCPs wired up: Perplexity, Context7, X, Composio, Agent Mail.
5. A loaded Obsidian-style second-brain workspace.
6. Watchdogs and email-based observability.
7. A Telegram channel for the customer-facing meta-agent.

## Quick start

```bash
git clone https://github.com/bobrapp/ai-bob-setup-agent.git
cd ai-bob-setup-agent
make install          # one-command bootstrap
cp .env.example .env  # then fill in your credentials
make doctor           # verifies the environment
make onboard CUSTOMER=acme-marketing
```

Full step-by-step setup: [install.html](https://bobrapp.github.io/ai-bob-setup-agent/install.html)

## The offer (what Bob sells, per the video)

- **Unlimited agents, unlimited usage, unlimited monitoring, security, and ongoing changes.**
- OpenClaw tier: ~$5K / mo. Hermes tier: ~$10K / mo.
- No token-talk, no credit-talk. The customer never sees a meter.
- Customers think they need 10-100 agents. In practice 1-3 do the work.

## Target verticals

**Pursue:** marketing, law, insurance, manufacturing, wholesale, real estate.
**Avoid (for now):** healthcare and finance — too regulated for a solo operator.

## The stack

| Layer | Tools |
|-------|-------|
| Customer-facing | Granola, Trello, Loom, Superhuman, Asana, Telegram |
| Agent runtime | Hermes, OpenClaw, Orgo |
| Connectors | Composio, Agent Mail, MCPs (Perplexity, Context7, X) |
| Knowledge | Obsidian (second-brain per customer) |
| Models | GPT 5.5 (default), GLM 5.1 / Kimmy (light), Opus 4.7 (long-horizon coding) |
| Operator tools | Codex, Claude Code |

## Documentation

- [Business Plan](https://bobrapp.github.io/ai-bob-setup-agent/bizplan.html)
- [Pitch Deck](https://bobrapp.github.io/ai-bob-setup-agent/pitch.html) — toggle between technical and business framings
- [PRD-FAQ](https://bobrapp.github.io/ai-bob-setup-agent/prdfaq.html) — Amazon working-backwards format
- [User Guide](https://bobrapp.github.io/ai-bob-setup-agent/userguide.html)
- [Install Guide](https://bobrapp.github.io/ai-bob-setup-agent/install.html)
- [Tool Stack](https://bobrapp.github.io/ai-bob-setup-agent/toolstack.html)
- [How I Built This](https://bobrapp.github.io/ai-bob-setup-agent/howibuilt.html)
- [Config](https://bobrapp.github.io/ai-bob-setup-agent/config.html)
- [Ops Dashboard](https://bobrapp.github.io/ai-bob-setup-agent/dashboard.html)
- [Spec](./docs/spec.md) · [Architecture](./docs/architecture.md) · [Build log](./docs/build-log.md)

## Project structure

```
ai-bob-setup-agent/
├── *.html                       # Public docs site (GitHub Pages)
├── assets/                      # Shared styles, fonts, images
├── docs/                        # Spec, architecture, source notes, build log
├── config/                      # Customer configs + stack definitions
│   ├── customers.example.yaml
│   └── stacks/                  # hermes.yaml, openclaw.yaml
├── scripts/                     # Operational scripts
├── src/                         # Python package (the setup agent)
├── tests/                       # Smoke tests
├── .github/workflows/           # CI + GitHub Pages deploy
├── install.sh                   # Idempotent bootstrap
├── Makefile                     # install / run / test / deploy / doctor
└── .env.example                 # Credentials and config knobs
```

## Status

v0.1 — repo skeleton with documentation site, functional script skeletons,
and a Telegram-controlled meta-agent stub. Real Orgo and Hermes API calls
are wired through clear extension points; bring your own keys to go live.

## Provenance

Every meaningful change to this repo is logged to
[`docs/build-log.md`](./docs/build-log.md) with UTC timestamp, operator, model,
prompt summary, result summary, and assets generated. This follows the
AIGovOps Foundation "how I built this" rule.

## License

MIT — see [LICENSE](./LICENSE).

## Credits

- Greg Isenberg ([@gregisenberg](https://x.com/gregisenberg)) — host of the source episode.
- Nick Vasilescu ([@nickvasiles](https://www.youtube.com/@nickvasiles)) — Orgo founder, source of the playbook.
- Built by [bobrapp](https://github.com/bobrapp) as part of the AIGovOps Foundation initiative.
