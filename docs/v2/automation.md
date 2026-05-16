# Automation Design

## Agent Definitions (YAML-driven)

Every agent is a YAML file. No Python code per agent. The runtime engine interprets them.

### Agent YAML Schema

```yaml
agent:
  name: string              # e.g. "personal/email_classifier"
  description: string       # Human-readable purpose
  trigger: string           # Event pattern to subscribe to
  model: string             # litellm model identifier
  output_schema: string     # Pydantic model name for structured output
  system_prompt: string     # System prompt for the LLM
  temperature: float        # 0.0-1.0 (default 0.3)
  max_tokens: int           # Max response tokens (default 1024)
  policy: string            # Path to Cedar policy file
  timeout_seconds: int      # Max execution time (default 30)
  retry:
    max_attempts: int       # Default 3
    backoff: string         # "exponential" or "fixed"
    initial_delay_seconds: int

actions:                    # What to do with the output
  - when: string            # CEL expression evaluated against output
    do: string              # Action to execute
    params: dict            # Parameters for the action

schedule:                   # Optional cron-like schedule
  cron: string              # e.g. "0 7 * * 1-5" (weekdays at 7 AM)
  timezone: string          # e.g. "America/Los_Angeles"
```

### Available Actions

| Action | Description | Requires approval? |
|--------|-------------|-------------------|
| `queue_approval(type)` | Create an approval queue item | No (creates the item) |
| `send_telegram(message)` | Send notification to Bob/Ken | No |
| `call_integration(name, method, params)` | Call an external API | Policy-dependent |
| `emit_event(name, data)` | Emit an event for other agents | No |
| `update_state(table, data)` | Write to state store | Policy-dependent |
| `log_audit(summary)` | Write to audit log | No (always permitted) |

### Example Agent Definitions

**Email Classifier:**
```yaml
agent:
  name: personal/email_classifier
  description: Classifies incoming emails into 5 categories
  trigger: email.arrived
  model: groq/llama-3.1-70b-versatile
  output_schema: EmailClassification
  system_prompt: |
    Classify this email for Bob Rapp (AIGovOps Foundation co-founder).
    Categories: action-required, FYI-only, newsletter, spam, foundation-business.
  temperature: 0.1
  policy: policies/agents/email.cedar

actions:
  - when: "output.category == 'action-required' && output.confidence >= 0.70"
    do: emit_event
    params: { event: "email.needs_reply", data: "input" }
  - when: "output.category == 'FYI-only'"
    do: call_integration
    params: { name: "email", method: "archive", id: "input.id" }
  - when: "output.confidence < 0.70"
    do: queue_approval
    params: { type: "manual_review", description: "Low-confidence email classification" }
```

**Community Welcomer:**
```yaml
agent:
  name: foundation/welcomer
  description: Welcomes new Circle.so community members
  trigger: member.joined
  model: gpt-4o
  output_schema: WelcomeMessage
  system_prompt: |
    Write a welcome DM for a new AIGovOps Foundation community member.
    Be warm, brief (3-4 sentences), reference their profile detail.
  temperature: 0.6
  policy: policies/agents/welcomer.cedar
  retry:
    max_attempts: 5
    backoff: exponential
    initial_delay_seconds: 30

actions:
  - when: "true"
    do: call_integration
    params: { name: "circle", method: "send_dm", member_id: "input.member_id", body: "output.message" }
  - when: "input.interests.length > 0"
    do: call_integration
    params: { name: "circle", method: "apply_tags", member_id: "input.member_id", tags: "input.interests" }
```

---

## Scheduling

Agents can be triggered by events OR schedules:

| Schedule | Agent | What it does |
|----------|-------|-------------|
| `0 7 * * 1-5` | research_scanner | Daily scan at 7 AM weekdays |
| `0 8 * * 1-5` | digest_builder | Morning digest at 8 AM weekdays |
| `0 8 * * *` | task_stale_checker | Stale task reminders daily |
| `0 12 * * 0` | curator | Weekly curation Sunday noon |
| `0 18 * * 0` | newsletter_assembler | Newsletter draft Sunday 6 PM |
| `0 17 * * 5` | report_generator | Weekly reports Friday 5 PM |

Implemented via APScheduler (in-process, no external dependency).

---

## Workflow Chains

Agents can trigger other agents via events:

```
email.arrived
  → email_classifier
    → email.classified
      → email_drafter (if action-required)
        → approval.created
          → [human approves]
            → email.sent

member.joined
  → welcomer
    → member.welcomed
      → tag_applier
        → member.tagged

schedule.daily_0700
  → research_scanner
    → research.items_found
      → research_scorer
        → research.scored
          → digest_builder (at 0800)
            → telegram.digest_sent
```

---

## Dry-Run Mode

When `dry_run: true`:
- All LLM calls execute normally (you see what the agent would produce)
- All `call_integration` actions are logged but NOT executed
- All `queue_approval` actions execute normally (you see items in the queue)
- All `emit_event` actions execute normally (downstream agents trigger)
- Audit log entries are marked with `dry_run: true`

This means you can test the entire pipeline end-to-end without any external side effects.
