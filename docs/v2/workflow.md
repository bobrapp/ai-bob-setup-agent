# Workflow Design

## Daily Workflows

### Morning Routine (7:00–8:30 AM Pacific, weekdays)

```
07:00 ─── research_scanner triggers
           │
           ├── Queries Perplexity for AI governance publications (last 24h)
           ├── Scores each item against 4 Foundation pillars
           ├── Items scoring ≥4 → newsletter draft queue
           └── Emits: research.items_scored

08:00 ─── digest_builder triggers (on research.items_scored OR schedule)
           │
           ├── Collects scored items from research_scanner
           ├── Formats morning digest
           ├── Sends to Bob + Ken via Telegram
           └── If no items: sends "no high-relevance items today"

08:00 ─── task_stale_checker triggers
           │
           ├── Queries Asana for tasks open >7 days without update
           ├── Sends reminder to assignee via Telegram
           └── Logs each reminder to audit

08:00 ─── milestone_alerter triggers
           │
           ├── Finds milestones due within 3 days
           ├── Sends status summary to Bob + Ken
           └── Includes: milestone name, due date, blocking task count
```

### Continuous (all day)

```
email.arrived ─── email_classifier
                   │
                   ├── action-required (≥70% confidence)
                   │    └── email_drafter → Approval Queue → [Bob approves] → send
                   │
                   ├── FYI-only → archive + daily digest entry
                   │
                   ├── newsletter → archive + extract to research queue
                   │
                   ├── spam → archive (no action)
                   │
                   ├── foundation-business → Approval Queue (Bob reviews)
                   │
                   └── low confidence (<70%) → Approval Queue (manual review)

member.joined ─── welcomer
                   │
                   ├── Idempotency check (already welcomed?)
                   ├── Generate personalized DM → send (pre-approved by policy)
                   ├── Post welcome thread message
                   ├── Apply interest tags from profile
                   └── Log all actions to audit

post.published ─── moderator
                    │
                    ├── Classify: spam, toxicity, PII, scam, off-topic
                    │
                    ├── spam/scam >90% → flag + urgent Telegram (60s)
                    ├── toxic/PII >80% → flag + Telegram (5 min)
                    ├── off-topic >85% → draft redirect → Approval Queue
                    └── below thresholds → log only (no action)
```

### Weekly Workflows

```
SUNDAY 12:00 ─── curator
                  │
                  ├── Fetch posts from prior 7 days
                  ├── Filter to AI governance tagged
                  ├── Rank by engagement (reactions + comments)
                  ├── Select top 3-5
                  ├── Draft digest + member spotlight
                  ├── Queue for approval
                  └── If no qualifying posts → notify Bob, skip

SUNDAY 18:00 ─── newsletter_assembler
                  │
                  ├── Pull research digest (week's high-relevance items)
                  ├── Pull curator digest
                  ├── Pull flagged items
                  ├── Assemble newsletter draft
                  └── Queue for approval (must approve before Monday send)

FRIDAY 17:00 ─── report_generator
                  │
                  ├── Weekly project status report → Approval Queue
                  ├── Outreach pipeline report → Telegram (Bob)
                  └── Governance report (actions, failures, anomalies) → Approval Queue
```

### On-Demand Workflows

```
Bob sends Telegram: "/draft linkedin post about AI governance trends"
  └── writing_agent triggers
       ├── Generates 3 variants (short/medium/long)
       ├── Queues all three for selection
       └── Bob picks one → approves → (manual post to LinkedIn)

Bob sends Telegram: "/outreach John Smith, CTO at TechCorp, met at conference"
  └── outreach_manager triggers
       ├── Creates Asana task (pipeline: new)
       ├── Drafts first-contact message
       ├── Queues for approval
       └── On approval → sends email → updates pipeline to "first-contact-sent"

Ken sends Telegram: "/suspend foundation/moderator"
  └── orchestrator
       ├── Suspends moderator agent
       ├── Logs suspension to audit
       └── Confirms via Telegram
```

---

## Approval Queue Flow

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│ Agent drafts│────▶│ Queue item   │────▶│ Presented   │
│ an action   │     │ created      │     │ to operator │
└─────────────┘     └──────────────┘     └──────┬──────┘
                                                  │
                         ┌────────────────────────┼────────────────────────┐
                         ▼                        ▼                        ▼
                  ┌─────────────┐         ┌─────────────┐         ┌─────────────┐
                  │  APPROVE    │         │   REJECT    │         │    EDIT     │
                  │             │         │             │         │             │
                  │ Log approval│         │ Log reason  │         │ Replace     │
                  │ Execute     │         │ Notify agent│         │ content     │
                  │ action      │         │ (revise or  │         │ Re-present  │
                  │             │         │  discard)   │         │ for review  │
                  └─────────────┘         └─────────────┘         └─────────────┘
```

### Queue Rules
- Items expire after 24 hours → reminder sent to both Bob and Ken
- If >10 items pending → summary digest instead of individual notifications
- All approvals/rejections logged with reviewer identity and timestamp
- Rejected items can trigger agent revision → re-queue cycle

---

## Workflow Versioning

Workflows are defined in profile YAML files and can be versioned:

```yaml
# profiles/bob.v2.yaml — adds a new workflow
workflows:
  - name: "Daily Morning Routine"
    version: "1.0"
    # ... existing steps

  - name: "LinkedIn Content Pipeline"  # NEW in v2
    version: "1.0"
    trigger: "on_demand"
    steps:
      - writing_agent.create_linkedin_variants
      - approval_queue.present_variants
      - on_approval: notify_bob("Ready to post!")
```

To add a new workflow: copy your profile to a new version, add the workflow, promote to production.
