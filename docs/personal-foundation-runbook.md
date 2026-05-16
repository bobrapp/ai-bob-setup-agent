INTERNAL USE ONLY — not part of the ai-bob-setup-agent customer product

# Personal + Foundation Agent Automation — Runbook

## Overview

This system automates the personal and foundation operations of Bob Rapp and Ken Johnston,
co-founders of the AIGovOps Foundation. It runs 8 agents that handle email, calendar,
research, writing, tasks, community welcome, curation, and moderation — all coordinated
through a Telegram-based Approval Queue.

## Prerequisites

- Python 3.11+
- make, git, bash
- Telegram bot token (from @BotFather)
- Circle.so Admin API key + Headless Auth JWT
- Composio API key (Asana + Trello)
- Perplexity API key

## Install

```bash
make install-foundation
cp config/personal-foundation/config.example.yaml config/personal-foundation/config.yaml
# Fill in credentials
make doctor-foundation
```

## Daily Operations

The system runs as a long-lived process:

```bash
make run-foundation
```

This starts:
- The Orchestrator (manages Approval Queue + agent lifecycle)
- The Telegram bot listener (receives approve/reject/edit commands)
- Scheduled agent triggers (via Make.com webhooks)

## Agents

| Agent | Prefix | Domain | Schedule |
|-------|--------|--------|----------|
| Email_Agent | personal/ | Inbox triage + drafts | On email arrival |
| Calendar_Agent | personal/ | Scheduling + briefings | On meeting events |
| Research_Agent | personal/ | AI governance scan | Daily 07:00 Pacific |
| Writing_Agent | foundation/ | Content drafts | On request + Sunday 18:00 |
| Task_Agent | personal/ | Asana/Trello sync | Continuous + Friday 17:00 |
| Welcomer | foundation/ | New member onboarding | On member join |
| Curator | foundation/ | Weekly digest | Sunday 12:00 Pacific |
| Moderator | foundation/ | Content classification | On post publish |

## Telegram Commands

| Command | Effect |
|---------|--------|
| Approve button | Execute the queued action |
| Reject button | Reject with optional reason |
| Edit button | Replace draft content, re-present for approval |
| `/suspend <agent>` | Manually suspend an agent |
| `/resume <agent>` | Resume a suspended agent |
| `/status` | Show system status summary |

## Approval Queue

Every consequential action passes through the Approval Queue before execution.
Items expire after 24 hours (configurable), triggering a reminder to both Bob and Ken.
When >10 items are pending, a summary digest is sent instead of individual notifications.

## Observability

- **Audit log**: `logs/audit.jsonl` — append-only JSONL, one record per agent action
- **Weekly report**: Generated Friday 17:00 Pacific, queued for approval
- **Auto-suspension**: Agent suspended if failure rate > 10% in 24h window
- **Viewer**: `python scripts/audit_viewer.py --agent personal/email_agent --status failure`

## Audit Log Format

Each line in `logs/audit.jsonl`:

```json
{
  "seq": 42,
  "operator": "bobrapp",
  "timestamp": "2026-05-15T12:00:00+00:00",
  "action": "personal/email_agent:classify",
  "command": "classify email_id=abc123",
  "customer": "bob",
  "model": "gpt-5.5",
  "dry_run": false,
  "status": "success",
  "result_summary": "category=action-required confidence=0.92",
  "git_sha": "abc1234"
}
```

## Dry-Run Mode

Set `dry_run: true` in `config/personal-foundation/config.yaml` to log all intended
actions without executing any external API calls. Useful for testing the full pipeline.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `FileNotFoundError: Foundation config not found` | Missing config.yaml | Copy config.example.yaml |
| Agent suspended unexpectedly | Failure rate > 10% | Check audit log, fix root cause, `/resume` |
| No Telegram notifications | Bot token invalid | Verify token in config.yaml |
| Circle.so DMs failing | Headless Auth JWT expired | Regenerate JWT in Circle Admin |
| Approval Queue items piling up | Bob/Ken not reviewing | Check Telegram, clear backlog |
