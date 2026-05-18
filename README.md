# AIGovOps Bot

[![CI](https://github.com/bobrapp/ai-bob-setup-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/bobrapp/ai-bob-setup-agent/actions/workflows/ci.yml)

> A Telegram bot that runs AI agents for email triage, content drafting, research scanning, and community management. Policy-gated, cost-tracked, human-in-the-loop.

**Live:** https://aigovops-automation.fly.dev  
**Site:** https://bobrapp.github.io/ai-bob-setup-agent  
**Bot:** [@aigovops_bot](https://t.me/aigovops_bot) on Telegram

---

## What this does

One bot, running 24/7 on Fly.io, handling operations for the AIGovOps Foundation:

- **Email triage** — polls Gmail every 5 min, classifies into 5 categories, notifies on action-required
- **Content drafting** — `draft about [topic]` → AI writes in Foundation voice → approve/reject/edit
- **Research scanning** — `/research` → finds AI governance news, scores relevance
- **Cost tracking** — every LLM call tracked per-agent, `/costs` shows 7-day report
- **Policy engine** — Cedar-style YAML rules control what agents can and can't do
- **Audit trail** — every action logged, `/audit` shows recent history

## Quick start

```bash
git clone https://github.com/bobrapp/ai-bob-setup-agent.git
cd ai-bob-setup-agent
cp .env.example .env    # Fill in: TELEGRAM_BOT_TOKEN, OPENAI_API_KEY, IMAP_PASSWORD
python3 -m pytest tests/ -v  # 83 tests pass
python3 scripts/run_bot.py   # Run locally
```

## Deploy to Fly.io

```bash
fly launch                    # First time
fly secrets set TELEGRAM_BOT_TOKEN="..." OPENAI_API_KEY="..." IMAP_PASSWORD="..."
fly deploy --ha=false --yes   # Ship it
```

## Telegram commands

| Command | What it does |
|---------|-------------|
| `draft about [topic]` | AI drafts a LinkedIn post |
| `classify [email text]` | Classify an email manually |
| `/research` | Scan for AI governance news |
| `/costs` | 7-day cost report by agent |
| `/status` | System health check |
| `/audit` | Last 10 actions from audit trail |
| `/help` | Show all commands |

## Architecture

```
Bob/Ken (Telegram) ←→ run_bot.py (Fly.io)
                         ├── Email poller (IMAP, 5 min)
                         ├── PolicyEngine (Cedar-style YAML rules)
                         ├── CostTracker (per-agent, per-model)
                         ├── StateStore (SQLite on persistent volume)
                         └── Audit log (append-only)
                              ↕
                         OpenAI GPT-4o-mini
```

Single process. SQLite. No Redis. No Kubernetes. Runs on a $5/mo Fly.io VM.

## Project structure

```
ai-bob-setup-agent/
├── scripts/
│   ├── run_bot.py              ← The bot (entry point)
│   ├── email_poller.py         ← IMAP polling + classification
│   └── generate_cost_data.py   ← Cost dashboard data
├── src/personal_foundation/v2/ ← Engine
│   ├── state.py                ← SQLite state store
│   ├── policy.py               ← Policy engine
│   ├── cost_tracker.py         ← LLM cost tracking
│   ├── event_bus.py            ← Event pub/sub
│   ├── engine.py               ← Agent runtime
│   ├── cache.py                ← LLM response cache
│   └── feedback.py             ← Learning from edits
├── agents/*.yaml               ← Agent definitions (5)
├── policies/*.yaml             ← Policy rules
├── tests/                      ← 83 tests
├── data/                       ← SQLite DB (gitignored)
├── Dockerfile                  ← Production container
├── fly.toml                    ← Fly.io config
└── *.html                      ← Dashboard + demo pages
```

## Agents

| Agent | Model | Trigger | Role |
|-------|-------|---------|------|
| Email Classifier | gpt-4o-mini | email.arrived | Classify into 5 categories |
| Writing Agent | gpt-4o-mini | draft command | LinkedIn posts in Foundation voice |
| Research Scanner | gpt-4o-mini | daily / on-demand | AI governance news digest |
| Welcomer | gpt-4o-mini | member.joined | Personalized community DMs |
| Moderator | gpt-4o-mini | post.published | Flag (never delete) off-topic content |

## Costs

Running cost: **~$5-10/month** total (Fly.io $5 + OpenAI ~$2-5 for GPT-4o-mini).

The `/costs` command and `costs.html` dashboard show real-time per-agent breakdowns.

## Tests

```bash
python3 -m pytest tests/ -v   # 83 pass, ~2 seconds
```

## License

MIT — see [LICENSE](./LICENSE).

## Credits

Built by [Bob Rapp](https://github.com/bobrapp) and Ken Johnston as part of the AIGovOps Foundation.
