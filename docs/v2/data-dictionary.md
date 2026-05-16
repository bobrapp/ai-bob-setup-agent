# Data Dictionary

## Database Schema (SQLite + SQLCipher)

### Table: `audit_log`

The immutable record of every agent action. Append-only — no UPDATE or DELETE permitted.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| seq | INTEGER | NO | Auto-increment primary key |
| timestamp | TEXT | NO | ISO 8601 UTC timestamp |
| operator | TEXT | NO | Who triggered/approved (bob, ken, system) |
| agent | TEXT | NO | Prefixed agent name (personal/email_agent) |
| action | TEXT | NO | Action verb (classify, draft, send_dm) |
| model | TEXT | YES | LLM model used (groq/llama-3.1-70b, gpt-4o) |
| prompt_summary | TEXT | YES | Max 200 chars, no secrets or PII |
| result_summary | TEXT | YES | Max 200 chars, no secrets or PII |
| status | TEXT | NO | success, failure, partial |
| dry_run | INTEGER | NO | 0 or 1 |
| policy_result | TEXT | YES | permit or deny + policy file reference |
| git_sha | TEXT | YES | Short SHA of running code |
| details_json | TEXT | YES | Structured metadata (JSON, no PII) |
| created_at | TEXT | NO | Server timestamp (redundant with timestamp for indexing) |

**Indexes:** `idx_audit_agent`, `idx_audit_timestamp`, `idx_audit_status`

---

### Table: `approval_queue`

Pending, approved, and rejected approval items.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| id | TEXT | NO | UUID primary key |
| agent | TEXT | NO | Agent that created the item |
| action_type | TEXT | NO | email_draft, weekly_digest, redirect_comment, etc. |
| description | TEXT | NO | Plain-language description for operator |
| draft_content | TEXT | NO | The actual draft or decision text |
| rationale | TEXT | YES | Editorial rationale (Writing Agent) |
| status | TEXT | NO | pending, approved, rejected, edited |
| reviewer | TEXT | YES | Who approved/rejected (bob, ken) |
| reviewed_at | TEXT | YES | ISO 8601 UTC |
| rejection_reason | TEXT | YES | Why it was rejected |
| created_at | TEXT | NO | ISO 8601 UTC |
| expires_at | TEXT | NO | created_at + 24h (triggers reminder) |

**Indexes:** `idx_queue_status`, `idx_queue_created`

---

### Table: `profiles`

Versioned operator profiles.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| operator | TEXT | NO | bob, ken |
| version | TEXT | NO | Semantic version (1.0.0) |
| stage | TEXT | NO | staging, production |
| config_yaml | TEXT | NO | Full profile YAML content |
| created_at | TEXT | NO | When this version was created |
| promoted_at | TEXT | YES | When promoted to production |

**Primary key:** (operator, version)

---

### Table: `events`

Event bus persistence. Events survive restarts.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| id | INTEGER | NO | Auto-increment |
| event_type | TEXT | NO | email.arrived, member.joined, schedule.* |
| payload_json | TEXT | NO | Event data (JSON) |
| processed | INTEGER | NO | 0 = unprocessed, 1 = processed |
| processed_by | TEXT | YES | Agent that consumed this event |
| created_at | TEXT | NO | ISO 8601 UTC |
| processed_at | TEXT | YES | When it was consumed |

**Indexes:** `idx_events_type_processed`, `idx_events_created`

---

### Table: `outreach_contacts`

Outreach pipeline state.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| id | TEXT | NO | UUID primary key |
| name | TEXT | NO | Contact name |
| email | TEXT | YES | Contact email (encrypted) |
| pipeline_stage | TEXT | NO | new, first-contact-sent, responded-interested, etc. |
| asana_task_id | TEXT | YES | Linked Asana task |
| last_contact_at | TEXT | YES | ISO 8601 UTC of last sent/received message |
| notes | TEXT | YES | Context notes |
| created_at | TEXT | NO | When added to pipeline |
| updated_at | TEXT | NO | Last stage change |

**Indexes:** `idx_contacts_stage`, `idx_contacts_last_contact`

---

### Table: `agent_state`

Runtime state for agents (e.g., rate limiter counters, last scan time).

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| agent | TEXT | NO | Agent name (primary key) |
| state_json | TEXT | NO | Agent-specific state (JSON) |
| suspended | INTEGER | NO | 0 = active, 1 = suspended |
| suspended_reason | TEXT | YES | Why suspended |
| suspended_at | TEXT | YES | When suspended |
| last_run_at | TEXT | YES | Last successful execution |
| failure_count_24h | INTEGER | NO | Failures in rolling 24h window |
| total_actions | INTEGER | NO | Lifetime action count |

---

### Table: `config`

Runtime configuration (managed via API, not files).

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| key | TEXT | NO | Config key (primary key) |
| value | TEXT | NO | Config value (may be JSON) |
| updated_at | TEXT | NO | Last update timestamp |
| updated_by | TEXT | NO | Who changed it |

---

## Data Types Reference

### PipelineStage (enum)
```
new → first-contact-sent → responded-interested → partner-confirmed
                         → responded-not-interested → archived
                         → needs-more-info → (loops back to first-contact-sent)
```

### ApprovalStatus (enum)
```
pending → approved → (action executed)
        → rejected → (agent revises or discards)
        → edited → (re-presented for approval)
```

### AgentStatus (enum)
```
active → suspended (auto or manual) → active (on /resume)
```

### EventTypes
```
email.arrived          — new email detected
email.classified       — email classified by agent
email.sent             — email sent after approval
member.joined          — new Circle.so member
member.welcomed        — welcome DM sent
post.published         — new community post
post.classified        — post moderation complete
post.flagged           — post flagged for review
research.items_scored  — daily scan complete
approval.created       — new item in queue
approval.approved      — item approved by operator
approval.rejected      — item rejected by operator
agent.suspended        — agent auto/manually suspended
agent.resumed          — agent resumed
schedule.*             — cron-triggered events
```

---

## Data Retention

| Data | Retention | Reason |
|------|-----------|--------|
| Audit log | Forever (append-only) | Compliance, provenance |
| Approval queue items | 90 days | Historical reference |
| Events (processed) | 7 days | Debugging only |
| Outreach contacts | Until archived | Active pipeline |
| Agent state | Current only | Runtime state |
| Profiles | All versions forever | Rollback capability |

---

## Data Protection Rules

1. **Email bodies** — NEVER stored. Only: sender, subject, message_id, classification result.
2. **Post content** — NEVER stored in audit. Only: post_id, classification scores.
3. **Member names** — NEVER in audit. Only: member_id (opaque identifier).
4. **API keys** — NEVER in database. Stored in system keychain only.
5. **Draft content** — Stored in approval_queue table (needed for review). Purged after 90 days.
6. **Contact emails** — Encrypted in outreach_contacts table (SQLCipher handles this).
