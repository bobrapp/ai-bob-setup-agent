# Implementation Tasks

## Task 1: Package scaffold and config layer

Set up the `src/personal_foundation/` package with the base infrastructure that all agents depend on.

- [x] 1.1 Create `src/personal_foundation/__init__.py` (empty, marks package)
- [x] 1.2 Create `src/personal_foundation/config.py` with Pydantic models: `TelegramFoundationConfig`, `CircleConfig`, `ComposioConfig`, `PerplexityConfig`, `FoundationConfig` (all fields from design doc); include `load_config()` that reads from `config/personal-foundation/config.yaml` and validates
- [x] 1.3 Create `src/personal_foundation/audit_shim.py` — thin wrapper over `src/audit_log.py` that enforces `personal/` or `foundation/` prefix on every `action` field; raise `ValueError` if caller passes an unprefixed action
- [x] 1.4 Create `src/personal_foundation/agents/__init__.py` and `BaseAgent` class with `agent_prefix`, `agent_name`, `__init__(config, dry_run)`, `log(action, command, **kwargs)`, and `queue(item)` methods
- [x] 1.5 Create `config/personal-foundation/` directory with a `config.example.yaml` documenting all required keys; add `config/personal-foundation/` to `.gitignore`
- [x] 1.6 Add `install-foundation` and `doctor-foundation` targets to `Makefile`

**Requirements:** 11.9, 13.1, 13.2, 13.5

---

## Task 2: ApprovalQueue and Orchestrator

Implement the Approval_Queue state machine and Orchestrator that all agents use to surface decisions to Bob and Ken.

- [x] 2.1 Create `src/personal_foundation/approval_queue.py` with `ApprovalItem` dataclass (all fields from design) and `ApprovalQueue` class with `enqueue`, `approve`, `reject`, `edit`, `pending`, and `overdue` methods; store items in an in-memory dict keyed by `item_id`
- [ ] 2.2 Create `src/personal_foundation/orchestrator.py` with `Orchestrator` class implementing: `present_to_telegram`, `handle_approval` (log-then-execute within 2 min), `handle_rejection` (log + notify agent), `handle_edit` (replace draft + re-present), `suspend_agent`, `resume_agent`, `is_suspended`, `weekly_governance_report`, `check_failure_rates`
- [ ] 2.3 Implement the 24-hour overdue reminder loop in `Orchestrator` — poll `approval_queue.overdue()` every 5 minutes; send Telegram reminder to both Bob and Ken when an item crosses the 24h threshold
- [ ] 2.4 Implement the 10-item digest threshold — when `len(approval_queue.pending()) > 10`, send a summary digest to Bob instead of individual notifications
- [ ] 2.5 Implement agent failure rate tracking in `Orchestrator` — read from `logs/audit.jsonl`; when any agent's failure rate exceeds 10% in a 24h window, suspend it and notify Bob within 60 seconds; support `/resume <agent>` Telegram command

**Requirements:** 12.1–12.8, 10.4–10.6

---

## Task 3: Integration clients

Implement the five integration client wrappers. These can be built in parallel.

- [x] 3.1 Create `src/personal_foundation/integrations/__init__.py`
- [x] 3.2 Create `src/personal_foundation/integrations/circle_client.py` — `CircleClient` wrapping Circle Admin API with methods: `get_member`, `send_dm` (Headless Auth JWT), `post_to_space`, `apply_tag`, `flag_post`, `list_recent_posts`, `get_post_engagement`; all methods check `dry_run` flag and log instead of calling API when set
- [ ] 3.3 Create `src/personal_foundation/integrations/composio_client.py` — `ComposioClient` wrapping Composio for Asana and Trello: `create_asana_task`, `update_asana_task`, `complete_asana_task`, `get_asana_task`, `update_trello_card`; dry_run aware
- [ ] 3.4 Create `src/personal_foundation/integrations/granola_client.py` — `GranolaClient` with `get_meeting_notes(meeting_id)` returning title, date, summary/transcript; dry_run aware
- [ ] 3.5 Create `src/personal_foundation/integrations/perplexity_client.py` — `PerplexityClient` with `search(query, max_age_hours=24)` returning list of `ResearchItem` stubs (url, title, published_at); dry_run aware
- [ ] 3.6 Create `src/personal_foundation/integrations/make_shim.py` — FastAPI app with `POST /make-shim/scenario-complete` endpoint; validates payload, calls `audit_shim.log` with `foundation/make_shim:scenario_complete`

**Requirements:** 11.1–11.7

---

## Task 4: Data models

Implement the shared data model dataclasses used across agents.

- [x] 4.1 Create `src/personal_foundation/models.py` with: `ResearchItem` (with `to_json()` / `from_json()` round-trip methods), `OutreachContact`, `PipelineStage` enum, `CirclePost` (with `engagement` property), `WeeklyGovernanceReport`
- [x] 4.2 Add `EmailClassification` dataclass with `category: str`, `confidence: float`, `subject_line: str | None` fields
- [x] 4.3 Add `MeetingBriefing` dataclass with `attendee_backgrounds`, `recent_notes`, `suggested_agenda` fields

**Requirements:** 1.1, 3.2, 9.1, 10.4

---

## Task 5: Email Agent

Implement `Email_Agent` for inbox triage and draft reply generation.

- [ ] 5.1 Create `src/personal_foundation/agents/email_agent.py` with `EmailAgent(BaseAgent)` class
- [ ] 5.2 Implement `classify(email) -> EmailClassification` — calls LLM to classify into one of 5 categories with confidence score; returns low-confidence flag if < 70%
- [ ] 5.3 Implement `process(email)` — routes based on classification: action-required → draft reply → queue; FYI-only → archive + digest; newsletter → archive + extract to research queue; spam → archive; foundation-business → queue; low-confidence → flag for manual review
- [ ] 5.4 Implement `draft_reply(email) -> str | None` — generates subject line + body; returns None on failure; on failure, queues item with failure note (Req 1.10)
- [ ] 5.5 Implement rate limiter — track emails processed per hour; block processing if at 50/hr limit
- [ ] 5.6 Implement outreach response routing (Req 9.3–9.5) — when email is from an outreach contact, classify as interested/not-interested/needs-more-info and update `OutreachContact.pipeline_stage` via `ComposioClient`

**Requirements:** 1.1–1.10, 9.3–9.5

---

## Task 6: Calendar Agent

Implement `Calendar_Agent` for scheduling and meeting preparation.

- [ ] 6.1 Create `src/personal_foundation/agents/calendar_agent.py` with `CalendarAgent(BaseAgent)` class
- [ ] 6.2 Implement `handle_meeting_request(request)` — check availability; if unavailable, propose 3 alternatives within next 5 business days 09:00–18:00 Pacific; queue scheduling decision
- [ ] 6.3 Implement `generate_briefing(meeting)` — fetch 5 most recent Granola notes with overlapping attendees; compile attendee backgrounds; generate suggested agenda; return `MeetingBriefing`
- [ ] 6.4 Implement `post_meeting_followup(meeting)` — retrieve Granola notes; extract action items; create Asana tasks via `ComposioClient` within 30 min; unresolved assignee → assign to Bob with note
- [ ] 6.5 Implement `update_recurring_context(series_id, session_notes)` — append decisions and action items to the series context document
- [ ] 6.6 Implement `handle_cancellation(meeting)` — release time block; suggest alternative use (focused work / admin catch-up / rest); attempt Telegram notification; log failure if notification fails without blocking

**Requirements:** 2.1–2.7

---

## Task 7: Research Agent

Implement `Research_Agent` for daily AI governance research scanning and digest delivery.

- [ ] 7.1 Create `src/personal_foundation/agents/research_agent.py` with `ResearchAgent(BaseAgent)` class
- [ ] 7.2 Implement `run_daily_scan() -> list[ResearchItem]` — query `PerplexityClient.search` for items published in prior 24h on AI governance / responsible AI / AI regulation; on Perplexity failure, log + notify Bob + return empty list
- [ ] 7.3 Implement `score_item(item) -> ResearchItem` — LLM scores relevance to each of the 4 Foundation pillars (1–5); set `relevance_score` to max pillar score; generate ≤150-word summary if score ≥ 4
- [ ] 7.4 Implement `deliver_digest(items)` — send high-relevance items (score ≥ 4) to Bob via Telegram by 08:00 Pacific; if no items, send "no high-relevance items" message; on Telegram failure, log + retry once after 15 min; log second failure without further retry
- [ ] 7.5 Implement `add_to_newsletter_draft(item)` — append scored item summary to the weekly newsletter draft file
- [ ] 7.6 Ensure `ResearchItem.to_json()` / `from_json()` round-trip is deterministic (same input → same output on re-parse)

**Requirements:** 3.1–3.10

---

## Task 8: Writing Agent

Implement `Writing_Agent` for content drafting and newsletter assembly.

- [ ] 8.1 Create `src/personal_foundation/agents/writing_agent.py` with `WritingAgent(BaseAgent)` class
- [ ] 8.2 Implement `create_draft(request, content_type) -> str` — generate draft in Foundation voice (practitioner-first, no superlatives, no CTAs); queue via `ApprovalQueue`; never call any publication API directly
- [ ] 8.3 Implement `create_linkedin_variants(request) -> tuple[str, str, str]` — generate short (50–100w), medium (150–250w), long-form (400–600w) variants
- [ ] 8.4 Implement `assemble_newsletter()` — triggered Sunday 18:00 Pacific; pull Research_Agent weekly digest + Curator digest + flagged items; assemble draft; queue by Sunday 18:00 Pacific
- [ ] 8.5 Implement `revise_draft(item_id, feedback)` — if feedback requires no new sourcing/format change, revise and requeue within 10 min; if new sourcing or format change required, notify Bob/Ken of estimated time (≤60 min) before proceeding
- [ ] 8.6 Add voice validation helper `_validate_voice(text) -> list[str]` — returns list of violations (superlatives found, CTAs found); used in tests

**Requirements:** 4.1–4.8

---

## Task 9: Task Agent

Implement `Task_Agent` for task tracking, project status, and outreach coordination.

- [ ] 9.1 Create `src/personal_foundation/agents/task_agent.py` with `TaskAgent(BaseAgent)` class
- [ ] 9.2 Implement `create_task_from_meeting(action_item, meeting_ref)` — create Asana task via `ComposioClient`; default due date = 5 business days; unresolved assignee → Bob with note
- [ ] 9.3 Implement `check_stale_tasks()` — scan Asana for tasks open > 7 days without any update (status change, comment, due-date change, assignee change); send Telegram reminder to assignee
- [ ] 9.4 Implement `sync_trello_on_completion(asana_task_id)` — when Asana task completes, update corresponding Trello card; if no Trello card found, log to Audit_Logger and stop
- [ ] 9.5 Implement `milestone_morning_alert()` — run at 08:00 Pacific daily; find milestones ≤ 3 days away; send status summary (milestone name, due date, count of open blocking tasks) to Bob and Ken
- [ ] 9.6 Implement `weekly_status_report()` — triggered Friday 17:00 Pacific; compile all active Foundation projects; queue in Approval_Queue
- [ ] 9.7 Implement outreach methods: `add_outreach_contact(name)` → create Asana task + queue first-contact draft; `check_followup_due()` → draft follow-up for contacts with no interaction in 7 days (retry up to 3× at 60s intervals on failure); `weekly_outreach_report()` → deliver to Bob via Telegram Friday 17:00 Pacific

**Requirements:** 5.1–5.6, 9.1–9.7

---

## Task 10: Welcomer

Implement the `Welcomer` for Circle.so new member onboarding.

- [ ] 10.1 Create `src/personal_foundation/agents/welcomer.py` with `Welcomer(BaseAgent)` class
- [ ] 10.2 Implement `welcome(member_id, join_event_id)` — idempotency check: query Audit_Logger for prior DM record for `(member_id, join_event_id)`; if found, skip and log; if not found, proceed
- [ ] 10.3 Implement `send_welcome_dm(member)` — personalize using member's role/org/AI governance interest from profile; call `CircleClient.send_dm`; log with member_id (not PII), model, personalization element
- [ ] 10.4 Implement `post_welcome_thread(member)` — post to welcome space tagging member; highlight one community resource matched to member's interests
- [ ] 10.5 Implement `apply_interest_tags(member)` — map profile keywords to defined Circle.so interest tags; call `CircleClient.apply_tag` for each match
- [ ] 10.6 Implement exponential backoff retry for Circle.so API failures — start at 30s, double each attempt, max 30-min window; on exhaustion, log failure + notify Bob via Telegram

**Requirements:** 6.1–6.6

---

## Task 11: Curator

Implement the `Curator` for weekly community digest and content amplification.

- [ ] 11.1 Create `src/personal_foundation/agents/curator.py` with `Curator(BaseAgent)` class
- [ ] 11.2 Implement `run_weekly_curation()` — triggered Sunday 12:00 Pacific; fetch posts from prior 7 days via `CircleClient.list_recent_posts`; filter to AI governance tagged posts; rank by `engagement` (reactions + comments); select top 3–5
- [ ] 11.3 Implement `draft_digest(top_posts) -> str` — draft weekly digest post summarizing top posts; draft member spotlight for highest-engagement contributor (name, post title, one-sentence description); queue both in Approval_Queue
- [ ] 11.4 Handle zero-qualifying-posts case — notify Bob via Telegram that no qualifying posts were found; skip digest for that week
- [ ] 11.5 Implement `publish_digest(item_id)` — on approval, call `CircleClient.post_to_space`; if no success response within 5 min, mark as failed, log, require re-approval before retry
- [ ] 11.6 Implement `check_inactive_threads()` — find threads inactive > 14 days with engagement ≥ 5; draft bump comment; queue in Approval_Queue

**Requirements:** 7.1–7.7

---

## Task 12: Moderator

Implement the `Moderator` for community content classification and flagging.

- [ ] 12.1 Create `src/personal_foundation/agents/moderator.py` with `Moderator(BaseAgent)` class
- [ ] 12.2 Implement `classify_post(post) -> dict` — LLM classifies for spam, toxicity, PII exposure, scam links, off-topic; returns `{category: str, confidence: float}` for each dimension; complete within 5 min of post publication
- [ ] 12.3 Implement `act_on_classification(post, results)` — route based on confidence thresholds: spam/scam > 90% → flag + Telegram within 60s; toxic/PII > 80% → flag + Telegram within 5 min; off-topic > 85% → draft ≤280-char redirect comment → queue; below threshold → log only
- [ ] 12.4 Implement Telegram notification retry — on failure, retry once after 60s; log second failure without further retry
- [ ] 12.5 Enforce no-auto-remove invariant — `Moderator` MUST NOT call any Circle.so delete or hide endpoint; all removal actions require explicit Approval_Queue approval

**Requirements:** 8.1–8.8

---

## Task 13: Governance reporting and audit log viewer

Implement the weekly governance report and read-only audit log viewer.

- [ ] 13.1 Implement `Orchestrator.weekly_governance_report()` — reads `logs/audit.jsonl`; computes total actions, actions by agent, approval queue throughput, failure rate per agent, anomalies (>10% failure rate or >5 consecutive failures); formats as readable report; queues in Approval_Queue Friday 17:00 Pacific; on delivery failure, retry once after 15 min
- [ ] 13.2 Create `scripts/audit_viewer.py` — CLI tool that reads `logs/audit.jsonl` and displays last 100 entries with `--agent`, `--date`, `--status` filter flags; output to stdout in a readable table format

**Requirements:** 10.1–10.9

---

## Task 14: Property-based tests (Hypothesis)

Implement all 10 correctness property tests using Hypothesis.

- [ ] 14.1 Create `tests/test_pbt_personal_foundation.py` with Hypothesis strategies for `AuditEntry`, `ResearchItem`, `ApprovalItem`, `CirclePost`, `OutreachContact`, `EmailMessage`
- [ ] 14.2 Property 1 — Audit log JSONL round-trip: `@given(AuditEntry)` → serialize to JSONL line → deserialize → assert all fields equal; `max_examples=200`
- [ ] 14.3 Property 2 — Research item round-trip: `@given(ResearchItem)` → `to_json()` → `from_json()` → assert `pillar_scores` and `summary` equal; `max_examples=100`
- [ ] 14.4 Property 3 — Dry-run no external calls: `@given(agent_action, payload)` → run with `dry_run=True` → assert `httpx.Client` never called; `max_examples=100`
- [ ] 14.5 Property 4 — Approval_Queue item integrity: `@given(ApprovalItem)` → enqueue → retrieve from `pending()` → assert `agent`, `action_type`, `description`, `draft_content`, `created_at` unchanged; `max_examples=100`
- [ ] 14.6 Property 5 — Welcome DM idempotence: `@given(member_id, join_event_id)` → call `welcome()` twice → assert exactly 1 DM log entry for that `(member_id, join_event_id)`; `max_examples=100`
- [ ] 14.7 Property 6 — Moderator never auto-removes: `@given(CirclePost, confidence)` → `classify_and_act()` → assert `delete_post` and `hide_post` never called; `max_examples=100`
- [ ] 14.8 Property 7 — Agent prefix invariant: `@given(agent_class, action_name)` → `agent.log()` → assert last audit entry `action` starts with `personal/` or `foundation/`; `max_examples=100`
- [ ] 14.9 Property 8 — Email classification exhaustiveness: `@given(EmailMessage)` → `classify()` → if confidence ≥ 0.70, assert category in `VALID_CATEGORIES`; `max_examples=100`
- [ ] 14.10 Property 9 — Outreach retry exhaustion: `@given(OutreachContact)` → patch `_generate_followup_draft` to always raise → `draft_followup()` → assert called exactly 3 times; `max_examples=100`
- [ ] 14.11 Property 10 — Writing_Agent never publishes without approval: `@given(content_request, content_type)` → `create_draft()` → assert `post_to_space` and `smtplib.SMTP` never called; `max_examples=100`

**Requirements:** 3.10, 4.7, 6.5, 8.7, 10.8, 11.8, 12.1, 12.8, 13.2

---

## Task 15: Unit tests

Implement example-based unit tests for all agents and integrations.

- [ ] 15.1 `tests/test_email_agent.py` — 5 classification examples (one per category); confidence-below-70% flagging; rate-limit enforcement; draft failure fallback
- [ ] 15.2 `tests/test_calendar_agent.py` — alternative time proposal; Asana task creation from Granola notes; unresolved assignee fallback to Bob; cancellation notification failure path
- [ ] 15.3 `tests/test_research_agent.py` — pillar scoring (1–5); 150-word summary truncation; 08:00 Pacific scheduling; Perplexity failure path; no-high-relevance-items message
- [ ] 15.4 `tests/test_writing_agent.py` — voice validation (superlatives rejected); three LinkedIn variant word counts; revision-within-10-min path; new-sourcing notification path
- [ ] 15.5 `tests/test_task_agent.py` — 7-day stale task reminder; Trello sync on completion; missing Trello card logging; Friday 17:00 report generation; outreach retry max-3
- [ ] 15.6 `tests/test_welcomer.py` — tag application from profile keywords; exponential backoff timing (30s → 60s → 120s); 30-min window exhaustion
- [ ] 15.7 `tests/test_curator.py` — engagement ranking; 14-day inactive thread detection; zero-qualifying-posts path; 5-min publish timeout
- [ ] 15.8 `tests/test_moderator.py` — confidence threshold routing (90% spam, 80% toxic/PII, 85% off-topic); 280-char redirect enforcement; Telegram retry once
- [ ] 15.9 `tests/test_orchestrator.py` — 24-hour reminder; 10-item digest threshold; agent suspension/resume; failure rate calculation; log-then-execute order
- [ ] 15.10 `tests/test_audit_shim.py` — prefix enforcement (unprefixed action raises ValueError); dry_run flag propagation; JSONL append-only behavior
- [ ] 15.11 `tests/test_circle_client.py` — exponential backoff timing; 30-min window exhaustion; dry_run suppresses HTTP calls

**Requirements:** 1–13 (unit coverage)

---

## Task 16: Smoke tests and runbook

Add smoke tests to the existing test suite and write the internal runbook.

- [ ] 16.1 Add to `tests/test_smoke.py`: `make install-foundation` exits zero; `make doctor-foundation` exits zero with required env vars; `config/personal-foundation/` is in `.gitignore`; `src/personal_foundation/` has no import of `src.setup_agent` or `src.hermes_install`
- [ ] 16.2 Create `docs/personal-foundation-runbook.md` with first line `INTERNAL USE ONLY — not part of the ai-bob-setup-agent customer product`; document: system overview, prerequisites, install steps, daily operations, agent descriptions, Telegram commands, troubleshooting, audit log format

**Requirements:** 13.1, 13.4, 13.5

---

## Task 17: Add hypothesis to requirements and CI

Ensure Hypothesis is installed and CI runs the PBT suite.

- [ ] 17.1 Add `hypothesis>=6.100.0` to `requirements.txt`
- [ ] 17.2 Update `.github/workflows/ci.yml` to run `pytest tests/test_pbt_personal_foundation.py` in the test step; integration tests remain skipped in CI (marked `@pytest.mark.integration`)

**Requirements:** (testing infrastructure)
