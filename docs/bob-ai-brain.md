# Bob's AI Brain — Session Summary

## What This Is

This document captures the complete context of the AIGovOps Bot system. Use it to resume work in a new session.

---

## System Overview

**What exists (v3 — simplified):**
- Telegram bot running 24/7 on Fly.io
- 5 AI agents (Email Classifier, Writing, Research, Welcomer, Moderator)
- v2 engine: PolicyEngine, CostTracker, StateStore, EventBus, audit trail
- Email polling every 5 min (IMAP → classify → notify)
- 6 Telegram commands: draft, classify, /research, /costs, /status, /audit
- 83 tests passing
- Cost dashboard (costs.html) + ops dashboard (dashboard.html)

**What was archived (in `_archive/`, gitignored):**
- Customer provisioning system (Orgo/Hermes setup agent)
- aigovops-agent-framework PyPI package
- WhatsApp/SMS/Voice channels
- v1 orchestrator and agents
- SaaS multi-tenant layer
- 14 marketing HTML pages

**What's live:**
- Bot: https://aigovops-automation.fly.dev
- Site: https://bobrapp.github.io/ai-bob-setup-agent
- Repo: https://github.com/bobrapp/ai-bob-setup-agent

---

## Architecture (v3)

```
Bob/Ken (Telegram) ←→ run_bot.py (Fly.io)
                         ├── Email poller (IMAP, 5 min)
                         ├── PolicyEngine (Cedar-style YAML rules)
                         ├── CostTracker (per-agent, per-model)
                         ├── StateStore (SQLite on persistent volume)
                         └── Audit log (append-only)
                              ↕
                         OpenAI GPT-4o-mini + Gmail IMAP
```

Single process. SQLite. $5/mo Fly.io VM. ~$5/mo LLM costs.

---

## Key Files

```
scripts/run_bot.py              ← The bot (entry point, deployed)
scripts/email_poller.py         ← IMAP polling + classification
scripts/generate_cost_data.py   ← Cost dashboard data generator
src/personal_foundation/v2/     ← Engine (state, policy, costs, events, cache)
agents/*.yaml                   ← 5 agent definitions
policies/*.yaml                 ← Cedar-style policy rules
tests/                          ← 83 tests
data/                           ← SQLite DB (persistent Fly volume)
Dockerfile + fly.toml           ← Deployment
index.html, demo.html, dashboard.html, costs.html  ← Web pages
```

---

## Key Commands

```bash
# Deploy
fly deploy -a aigovops-automation --ha=false --yes

# Set secrets
fly secrets set -a aigovops-automation KEY="value"

# Check status
fly status -a aigovops-automation
curl https://aigovops-automation.fly.dev/

# View logs
fly logs -a aigovops-automation

# Run tests
python3 -m pytest tests/ -v

# Generate cost data for dashboard
python3 scripts/generate_cost_data.py
```

---

## Credentials (in Fly.io secrets + local .env)

| Service | Key name | Status |
|---------|----------|--------|
| Telegram bot | TELEGRAM_BOT_TOKEN | ✅ Active |
| Bob's Telegram | TELEGRAM_BOB_CHAT_ID | ✅ Active |
| Ken's Telegram | TELEGRAM_KEN_CHAT_ID | ⏳ Pending (Ken onboarding) |
| Gmail (IMAP) | IMAP_USER + IMAP_PASSWORD | ✅ Rotated |
| OpenAI | OPENAI_API_KEY | ✅ Rotated |
| Groq | GROQ_API_KEY | ⏳ Needs email verification |
| Perplexity | PERPLEXITY_API_KEY | ✅ Set |
| Circle.so | CIRCLE_API_KEY | ❌ 403 (plan limitation?) |
| Composio | COMPOSIO_API_KEY | ⏳ Needs email verification |

---

## What Needs Doing Next

### This week
1. ✅ Email polling live
2. ✅ Cost dashboard built
3. ✅ Simplified to v3 (archived dead code)
4. Verify Groq email → activate free fast model
5. Verify Composio email → activate integrations
6. Resolve Circle.so API access (plan upgrade or support ticket)

### Next week
7. Ken messages @aigovops_bot → get his chat ID
8. Add Ken's chat ID → redeploy
9. Connect Welcomer + Moderator to Circle.so (once API works)

### Future
10. Wire the v2 AgentEngine to run agents on events (not just bot commands)
11. Add scheduler for daily research digest (cron trigger)
12. Perplexity integration for real-time research (replace GPT-simulated results)

---

## Resume Prompt

> "I'm Bob Rapp. Continue building the AIGovOps Bot. The repo is at ~/ai-bob-setup-agent. Read docs/bob-ai-brain.md for context. Next: [your request]"
