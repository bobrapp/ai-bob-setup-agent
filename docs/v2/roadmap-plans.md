# Roadmap Execution Plans

## Plan 1: v2.1 — Production Hardening (This Weekend)

**Goal:** System runs 24/7 processing real events from real services.

### Tasks

| # | Task | File(s) | Depends on | Est. |
|---|------|---------|-----------|------|
| 1.1 | Wire APScheduler to event bus — emit `schedule.*` events on cron | `src/personal_foundation/v2/scheduler.py` | — | 30 min |
| 1.2 | IMAP email poller — connect to Gmail/Superhuman, emit `email.arrived` on new mail | `src/personal_foundation/v2/integrations/email_poller.py` | — | 1 hr |
| 1.3 | Circle.so webhook handler — parse incoming webhooks, emit `member.joined` / `post.published` | Update `api.py` `/webhooks/circle` | — | 30 min |
| 1.4 | Composio integration — wire Asana task creation and Trello sync to real API | `src/personal_foundation/v2/integrations/composio.py` | — | 1 hr |
| 1.5 | Perplexity integration — wire research scanner to real Perplexity API | `src/personal_foundation/v2/integrations/perplexity.py` | — | 45 min |
| 1.6 | Systemd service file + install script | `deploy/aigovops-v2.service`, `deploy/install-v2.sh` | 1.1–1.5 | 30 min |
| 1.7 | Health monitoring — UptimeRobot config + `/api/health` enrichment | Update `api.py` | 1.6 | 15 min |
| 1.8 | Backup cron — SQLite backup every 6h to `backups/` | `scripts/backup.sh`, crontab entry | 1.6 | 15 min |
| 1.9 | Smoke test — verify full pipeline with real credentials in dry-run | `tests/test_v2_smoke.py` | 1.1–1.5 | 30 min |
| 1.10 | HIBT build-log entry | `docs/build-log.md` | 1.9 | 10 min |

**Total estimate:** ~6 hours
**Deliverable:** `make run-v2` starts the system, processes real emails/events, survives reboots.

---

## Plan 2: v2.2 — Web PWA (Next Week)

**Goal:** Bob and Ken manage everything from their phones via a native-feeling web app.

### Tasks

| # | Task | File(s) | Depends on | Est. |
|---|------|---------|-----------|------|
| 2.1 | PWA scaffold — Vite + Svelte (or React) + TailwindCSS | `web/` directory | — | 1 hr |
| 2.2 | Auth screen — login with username/password, store JWT | `web/src/pages/Login.svelte` | 2.1 | 30 min |
| 2.3 | Approval Queue page — list pending items, approve/reject/edit buttons | `web/src/pages/Queue.svelte` | 2.2 | 2 hr |
| 2.4 | Audit Log page — filterable table (agent, status, date) | `web/src/pages/Audit.svelte` | 2.2 | 1.5 hr |
| 2.5 | Agents page — status cards, suspend/resume buttons | `web/src/pages/Agents.svelte` | 2.2 | 1 hr |
| 2.6 | Dashboard page — summary stats, charts (actions/day, failure rate) | `web/src/pages/Dashboard.svelte` | 2.2 | 1.5 hr |
| 2.7 | WebSocket real-time — connect to `/ws/events`, update UI live | `web/src/lib/ws.ts` | 2.3 | 1 hr |
| 2.8 | Push notifications — Web Push API registration + service worker | `web/src/sw.js`, `web/src/lib/push.ts` | 2.7 | 1.5 hr |
| 2.9 | PWA manifest + icons — installable on home screen | `web/public/manifest.json` | 2.1 | 30 min |
| 2.10 | Offline support — service worker caches UI shell | `web/src/sw.js` | 2.9 | 1 hr |
| 2.11 | Deploy — build + serve from FastAPI static files (or Vercel) | `Makefile` target | 2.1–2.10 | 30 min |
| 2.12 | Mobile testing — verify on iPhone + Android | — | 2.11 | 1 hr |

**Total estimate:** ~12 hours (2 days)
**Deliverable:** `https://your-server:8000` serves a PWA that works on phone + desktop with real-time updates.

---

## Plan 3: v2.3 — Intelligence Upgrade (Week 2)

**Goal:** Agents get smarter, cheaper, and learn from Bob's feedback.

### Tasks

| # | Task | File(s) | Depends on | Est. |
|---|------|---------|-----------|------|
| 3.1 | Response cache — diskcache with 1h TTL for identical prompts | `src/personal_foundation/v2/cache.py` | — | 1 hr |
| 3.2 | Cache integration — wrap LLM calls in engine.py with cache check | Update `engine.py` | 3.1 | 30 min |
| 3.3 | Feedback loop — when Bob edits a draft, store (input, edit) pair | `src/personal_foundation/v2/feedback.py` | — | 1 hr |
| 3.4 | Few-shot injection — include last 3 feedback examples in system prompt | Update `engine.py` | 3.3 | 1 hr |
| 3.5 | Confidence calibration — track predicted vs. actual accuracy per agent | `src/personal_foundation/v2/calibration.py` | — | 2 hr |
| 3.6 | Calibration dashboard — show accuracy trends in web UI | Update `web/src/pages/Dashboard.svelte` | 3.5, Plan 2 | 1 hr |
| 3.7 | Multi-model routing config — per-agent model override in YAML | Update `engine.py` | — | 30 min |
| 3.8 | RAG for research — index prior items in SQLite FTS5, query before scoring | `src/personal_foundation/v2/rag.py` | — | 2 hr |
| 3.9 | Deduplication — skip research items already seen (by URL hash) | Update research agent | 3.8 | 30 min |
| 3.10 | Cost tracking — log token usage per call, weekly cost report | `src/personal_foundation/v2/cost_tracker.py` | — | 1 hr |

**Total estimate:** ~11 hours (2 days)
**Deliverable:** 30-50% cost reduction, agents improve with use, no duplicate research items.

---

## Plan 4: v3.0 — Framework Extraction (Month 2)

**Goal:** Anyone can use this for their own organization.

### Tasks

| # | Task | File(s) | Depends on | Est. |
|---|------|---------|-----------|------|
| 4.1 | Extract core into `aigovops-framework/` package | New directory structure | — | 4 hr |
| 4.2 | Define public API — `Framework`, `Agent`, `Policy`, `EventBus`, `StateStore` | `aigovops_framework/__init__.py` | 4.1 | 2 hr |
| 4.3 | Plugin interface — `IntegrationPlugin` base class for custom integrations | `aigovops_framework/plugins.py` | 4.1 | 2 hr |
| 4.4 | Cookiecutter template — `cookiecutter gh:bobrapp/aigovops-template` | `template/` directory | 4.1 | 3 hr |
| 4.5 | PyPI packaging — `pyproject.toml`, build, publish | `pyproject.toml` | 4.1–4.3 | 1 hr |
| 4.6 | Documentation site — MkDocs with getting-started, API reference, examples | `docs-site/` | 4.1–4.4 | 4 hr |
| 4.7 | Example agents library — 20 pre-built YAML agents | `examples/agents/` | 4.1 | 3 hr |
| 4.8 | Migration guide — how to move from v2 to the framework | `docs-site/migration.md` | 4.5 | 1 hr |
| 4.9 | CI for the framework — test, lint, publish on tag | `.github/workflows/framework-ci.yml` | 4.5 | 1 hr |
| 4.10 | Launch blog post — "Introducing the AIGovOps Agent Framework" | `docs-site/blog/` | 4.6 | 2 hr |

**Total estimate:** ~23 hours (1 week)
**Deliverable:** `pip install aigovops-agent-framework` works. Cookiecutter creates a new project in 5 min.

---

## Plan 5: v3.1 — Voice-First (Month 2-3)

**Goal:** Bob manages agents while driving, cooking, or walking.

### Tasks

| # | Task | File(s) | Depends on | Est. |
|---|------|---------|-----------|------|
| 5.1 | Siri Shortcuts — "What's pending?" | `voice/siri/whats-pending.shortcut` | Plan 1 (API running) | 1 hr |
| 5.2 | Siri Shortcuts — "Approve all low-risk" | `voice/siri/approve-low-risk.shortcut` | 5.1 | 30 min |
| 5.3 | Siri Shortcuts — "Suspend [agent]" | `voice/siri/suspend.shortcut` | 5.1 | 30 min |
| 5.4 | Siri Shortcuts — "Daily summary" | `voice/siri/daily-summary.shortcut` | 5.1 | 30 min |
| 5.5 | Siri Shortcuts — "Draft about [topic]" | `voice/siri/draft.shortcut` | 5.1 | 30 min |
| 5.6 | Shortcuts bundle — shareable iCloud link | — | 5.1–5.5 | 30 min |
| 5.7 | Alexa Skill — interaction model (5 intents) | `voice/alexa/interaction-model.json` | Plan 1 | 2 hr |
| 5.8 | Alexa Skill — Lambda handler | `voice/alexa/lambda/index.py` | 5.7 | 2 hr |
| 5.9 | Alexa Skill — publish to Alexa Skills Store | — | 5.8 | 1 hr |
| 5.10 | Conversational mode — multi-turn via Telegram voice messages | Update `channels/telegram.py` | Plan 1 | 3 hr |
| 5.11 | Voice-to-draft — transcribe voice note → trigger writing agent | `src/personal_foundation/v2/voice_transcribe.py` | 5.10 | 2 hr |
| 5.12 | Documentation — voice command reference | `docs/v2/voice-commands.md` | 5.1–5.11 | 1 hr |

**Total estimate:** ~14 hours (3 days)
**Deliverable:** 5 Siri Shortcuts + Alexa Skill + voice notes in Telegram. Hands-free agent management.

---

## Plan 6: v3.2 — Multi-Tenant SaaS (Month 3-4, if demand)

**Goal:** Other organizations pay to use a hosted version.

### Tasks

| # | Task | File(s) | Depends on | Est. |
|---|------|---------|-----------|------|
| 6.1 | PostgreSQL migration — Alembic migrations from SQLite schema | `migrations/`, `alembic.ini` | — | 4 hr |
| 6.2 | Tenant model — `organizations` table, row-level security | `src/saas/models.py` | 6.1 | 3 hr |
| 6.3 | Tenant isolation — all queries scoped by `org_id` | Update all state store methods | 6.2 | 4 hr |
| 6.4 | Auth upgrade — OAuth2 (Google/GitHub login) via Auth0 or Clerk | `src/saas/auth.py` | 6.2 | 4 hr |
| 6.5 | Onboarding wizard (hosted) — web-based, no CLI | `web/src/pages/Onboarding.svelte` | Plan 2, 6.4 | 4 hr |
| 6.6 | Stripe billing — $50/mo per org, usage metering for LLM calls | `src/saas/billing.py` | 6.4 | 4 hr |
| 6.7 | Usage dashboard — per-org: actions, cost, agents, storage | `web/src/pages/OrgDashboard.svelte` | 6.6 | 3 hr |
| 6.8 | Container deployment — Dockerfile + docker-compose + fly.io config | `Dockerfile`, `fly.toml` | 6.1–6.3 | 3 hr |
| 6.9 | Rate limiting per tenant — prevent one org from consuming all resources | Update `api.py` middleware | 6.3 | 2 hr |
| 6.10 | Admin panel — super-admin view of all tenants, usage, health | `web/src/pages/Admin.svelte` | 6.7 | 3 hr |
| 6.11 | Terms of service + privacy policy | `legal/tos.md`, `legal/privacy.md` | — | 2 hr |
| 6.12 | Launch — landing page, pricing page, signup flow | `web/src/pages/Landing.svelte` | 6.5–6.6 | 4 hr |

**Total estimate:** ~40 hours (2 weeks)
**Deliverable:** `https://app.aigovops.community` — hosted SaaS, Stripe billing, multi-tenant.

---

## Summary Timeline

```
Week 1 (this weekend):  Plan 1 — Production Hardening     [6 hrs]
Week 2:                 Plan 2 — Web PWA                   [12 hrs]
Week 3:                 Plan 3 — Intelligence Upgrade      [11 hrs]
Month 2:               Plan 4 — Framework Extraction       [23 hrs]
Month 2-3:             Plan 5 — Voice-First                [14 hrs]
Month 3-4 (if demand): Plan 6 — Multi-Tenant SaaS         [40 hrs]
                                                    Total: ~106 hrs
```

## Decision Points

- **After Plan 1:** Is the system reliable enough for daily use? If yes → Plan 2.
- **After Plan 2:** Are Bob and Ken using it daily? If yes → Plan 3.
- **After Plan 3:** Are agents accurate enough? If yes → Plan 4.
- **After Plan 4:** Are 5+ orgs asking to use it? If yes → Plan 6. If not → Plan 5 (voice).
- **Plan 6 gate:** Only build if there are paying customers waiting. Don't build SaaS speculatively.
