# Architecture Design — v2

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      INTERFACES                              │
│                                                              │
│  ┌──────────┐  ┌──────────────┐  ┌───────────┐  ┌───────┐ │
│  │ Web PWA  │  │ Telegram Bot │  │ Voice/Siri│  │ CLI   │ │
│  └────┬─────┘  └──────┬───────┘  └─────┬─────┘  └───┬───┘ │
└───────┼────────────────┼────────────────┼────────────┼──────┘
        │                │                │            │
        ▼                ▼                ▼            ▼
┌─────────────────────────────────────────────────────────────┐
│                    API GATEWAY (FastAPI)                      │
│                                                              │
│  /api/queue      — Approval Queue CRUD                       │
│  /api/agents     — Agent status, suspend, resume             │
│  /api/audit      — Read audit log (filtered)                 │
│  /api/profiles   — Profile management                        │
│  /api/config     — Runtime configuration                     │
│  /ws/events      — WebSocket for real-time updates           │
│                                                              │
│  Auth: JWT (Bob + Ken only)                                  │
│  Rate limit: 100 req/min per operator                        │
└──────────────────────────┬──────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
┌──────────────┐  ┌────────────────┐  ┌──────────────┐
│POLICY ENGINE │  │   EVENT BUS    │  │ STATE STORE  │
│              │  │                │  │              │
│ Cedar rules  │  │ SQLite-backed  │  │ SQLite +     │
│ evaluate     │  │ pub/sub with   │  │ SQLCipher    │
│ every action │  │ polling        │  │              │
│ before exec  │  │                │  │ Tables:      │
│              │  │ Events:        │  │ - queue      │
│ Policies:    │  │ - email.*      │  │ - audit_log  │
│ - approval   │  │ - member.*     │  │ - profiles   │
│ - data       │  │ - schedule.*   │  │ - events     │
│ - agents     │  │ - agent.*      │  │ - contacts   │
│ - security   │  │ - approval.*   │  │ - config     │
└──────┬───────┘  └───────┬────────┘  └──────┬───────┘
       │                  │                   │
       └──────────────────┼───────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    AGENT RUNTIME ENGINE                       │
│                                                              │
│  Loads agent YAML definitions → subscribes to events →       │
│  calls LLM → evaluates policy → executes actions             │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Agent YAML definitions (hot-reloadable)              │    │
│  │                                                      │    │
│  │ email_classifier.yaml  │  welcomer.yaml              │    │
│  │ email_drafter.yaml     │  curator.yaml               │    │
│  │ research_scanner.yaml  │  moderator.yaml             │    │
│  │ calendar_briefer.yaml  │  task_manager.yaml          │    │
│  │ outreach_manager.yaml  │  report_generator.yaml      │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  LLM Layer: litellm + instructor                             │
│  Models: Groq (fast) → GPT-4o (quality) → fallback          │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                 EXTERNAL INTEGRATIONS                         │
│                                                              │
│  Circle.so  │  Composio  │  Perplexity  │  Granola          │
│  Telegram   │  Asana     │  Trello      │  Email (IMAP)     │
│                                                              │
│  All calls go through IntegrationClient base class:          │
│  - Respects dry_run flag                                     │
│  - Logs metadata (not content) to audit                      │
│  - Evaluates policy before execution                         │
│  - Handles retries with exponential backoff                  │
└─────────────────────────────────────────────────────────────┘
```

---

## Component Details

### API Gateway

- **Framework:** FastAPI (async, WebSocket support, auto-docs)
- **Auth:** JWT with HS256. Two tokens: one for Bob, one for Ken. Tokens stored in browser localStorage / Telegram session / Siri Shortcut.
- **Endpoints:** RESTful for CRUD, WebSocket for real-time event streaming to web UI
- **Deployment:** Single process via `uvicorn`. No container needed for 2 users.

### Policy Engine

- **Language:** Cedar (AWS open-source policy language)
- **Evaluation:** Every agent action is checked against policies before execution
- **Hot-reload:** Policy files watched for changes; no restart needed
- **Audit:** Every policy evaluation (permit/deny) is logged

### Event Bus

- **Implementation:** SQLite table with polling (simple, no Redis dependency)
- **Pattern:** Agents subscribe to event patterns (e.g., `email.*`, `schedule.daily_0700`)
- **Persistence:** Events survive restarts. Unprocessed events are replayed on startup.
- **Scaling:** For 2 operators and 10 agents, SQLite polling at 1s intervals is more than sufficient.

### State Store

- **Engine:** SQLite with SQLCipher encryption
- **Schema:** See Data Dictionary document
- **Backup:** Daily automated backup to a second file. Weekly to cloud (optional).
- **Migration:** Alembic-style versioned migrations in `migrations/` directory.

### Agent Runtime Engine

- **Single class:** `AgentRuntime` loads YAML, subscribes to events, calls LLM, evaluates policy, executes actions
- **Hot-reload:** Agent YAML files watched for changes. New/modified agents activate without restart.
- **Concurrency:** `asyncio` with semaphore limiting concurrent LLM calls (default: 3)
- **Dry-run:** Global flag that prevents all external API calls while still running the full pipeline

### LLM Layer

- **Router:** litellm handles model selection and fallback
- **Structured output:** instructor guarantees Pydantic model responses
- **Tiers:** FAST (Groq, classification) → QUALITY (GPT-4o, drafting) → FALLBACK (GPT-4o-mini)
- **Caching:** Identical prompts cached for 1 hour (reduces cost for repeated classifications)

---

## Data Flow Examples

### Email arrives → draft reply → approval → send

```
1. IMAP poll detects new email
2. Event: email.arrived {id, sender, subject, preview}
3. email_classifier agent triggers
4. LLM classifies → EmailClassification {category: "action-required", confidence: 0.92}
5. Policy check: "Can email_classifier queue an approval?" → PERMIT
6. Event: email.classified {id, category, confidence}
7. email_drafter agent triggers (subscribed to email.classified where category=action-required)
8. LLM drafts reply
9. Policy check: "Can email_drafter create approval item?" → PERMIT
10. Approval item created in state store
11. Event: approval.created {item_id, agent, description}
12. All interfaces notified (Telegram inline keyboard, Web push, Voice alert)
13. Bob taps "Approve" in Telegram
14. Policy check: "Can Bob approve this item?" → PERMIT
15. Event: approval.approved {item_id, reviewer: "bob"}
16. Email sent via integration client
17. Audit log: action=send_email, status=success, approved_by=bob
```

### New member joins → welcome

```
1. Circle.so webhook fires (or polling detects new member)
2. Event: member.joined {member_id, display_name, bio}
3. welcomer agent triggers
4. Policy check: "Has this member already been welcomed?" → query state store
5. LLM generates personalized DM
6. Policy check: "Can welcomer send DM without approval?" → PERMIT (welcome DMs are pre-approved by policy)
7. DM sent via Circle.so API
8. Welcome post created in welcome space
9. Interest tags applied
10. Audit log: action=welcome_dm, member_id=xxx, status=success
```

---

## Deployment Topology

```
Bob's MacBook (or $20/mo VPS)
│
├── uvicorn (API + WebSocket)     port 8000
├── Agent Runtime (async loop)    in-process
├── Telegram Bot (polling)        in-process
├── SQLite database               data/foundation.db
├── Cedar policies                policies/*.cedar
└── Agent definitions             agents/*.yaml

External:
├── Groq API (classification)
├── OpenAI API (drafting)
├── Circle.so API (community)
├── Composio API (Asana/Trello)
├── Perplexity API (research)
└── Telegram API (notifications)
```

Single process. No Docker. No Kubernetes. No Redis. No Postgres. Just Python + SQLite + the APIs you already pay for.
