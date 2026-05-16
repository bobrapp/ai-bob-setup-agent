# Get to Yes, Stay at Yes, Recover to Yes

## The AIGovOps Foundation Architecture for AI Services at Scale

---

## The Core Insight

Most systems are designed to scale. This system is designed to **never lie**.

The hard problem isn't serving 2 million users. The hard problem is: when an AI agent produces an artifact (an email, a post, a report, a decision), how do you know it's **correct, authorized, and traceable**? And how do you maintain that guarantee at scale?

This is the AIGovOps "Yes" framework:

- **Get to Yes** — prove the system works correctly before it touches real data
- **Stay at Yes** — maintain correctness guarantees while serving load
- **Recover to Yes** — when something breaks, return to a known-good state fast

---

## The Two-System Architecture

The key design decision: **the core never talks to the scale layer directly.**

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SCALE LAYER                                    │
│                   (stateless, disposable, cheap)                      │
│                                                                       │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐     │
│  │ Edge 1  │ │ Edge 2  │ │ Edge 3  │ │ Edge N  │ │ Edge N+1│     │
│  │ (SJC)   │ │ (IAD)   │ │ (LHR)   │ │ (SYD)   │ │ (auto)  │     │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘     │
│       │            │            │            │            │           │
│       └────────────┴────────────┴────────────┴────────────┘           │
│                                 │                                      │
│                    ┌────────────▼────────────┐                        │
│                    │     MESSAGE QUEUE        │                        │
│                    │  (write-ahead log)       │                        │
│                    │  Kafka / NATS / SQS      │                        │
│                    └────────────┬────────────┘                        │
└─────────────────────────────────┼────────────────────────────────────┘
                                  │
                    ══════════════╪══════════════  ← AIR GAP (async only)
                                  │
┌─────────────────────────────────┼────────────────────────────────────┐
│                        CORE LAYER                                     │
│              (stateful, immutable, mainframe-like)                    │
│                                                                       │
│  ┌──────────────────────────────▼──────────────────────────────┐    │
│  │                    INTAKE PROCESSOR                           │    │
│  │  Validates, deduplicates, applies policy BEFORE processing   │    │
│  └──────────────┬───────────────────────────────┬──────────────┘    │
│                 │                               │                    │
│  ┌──────────────▼──────────────┐  ┌────────────▼───────────────┐   │
│  │      POLICY ENGINE          │  │      STATE MACHINE          │   │
│  │                             │  │                             │   │
│  │  Cedar rules (immutable)    │  │  Every artifact has a       │   │
│  │  Evaluated BEFORE action    │  │  lifecycle:                  │   │
│  │  Evaluated AFTER action     │  │                             │   │
│  │  Evaluated on READ          │  │  draft → validated →        │   │
│  │                             │  │  approved → published →     │   │
│  │  Rules versioned + signed   │  │  monitored → archived       │   │
│  └──────────────┬──────────────┘  └────────────┬───────────────┘   │
│                 │                               │                    │
│  ┌──────────────▼───────────────────────────────▼──────────────┐    │
│  │                    TRUTH STORE                                │    │
│  │                                                              │    │
│  │  Append-only ledger (never modified, never deleted)          │    │
│  │  Every state transition recorded with:                       │    │
│  │    - Who (operator or agent identity)                        │    │
│  │    - What (action + artifact hash)                           │    │
│  │    - When (monotonic timestamp)                              │    │
│  │    - Why (policy rule that permitted it)                     │    │
│  │    - How (model + prompt hash, NOT content)                  │    │
│  │                                                              │    │
│  │  Implemented as: PostgreSQL + WAL + logical replication      │    │
│  │  Backup: continuous to S3 (point-in-time recovery)           │    │
│  └──────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Why Two Layers?

| Property | Scale Layer | Core Layer |
|----------|-------------|-----------|
| Purpose | Handle load | Maintain truth |
| Scaling | Horizontal (add nodes) | Vertical (bigger machine) |
| State | Stateless | Stateful (single source of truth) |
| Failure mode | Node dies → others take over | NEVER dies (redundant, replicated) |
| Data | Ephemeral (cache, queues) | Permanent (append-only ledger) |
| Security | Edge protection (WAF, rate limit) | Deep protection (policy, signing) |
| Cost | Cheap (scale to zero) | Fixed (always on, always correct) |
| Analogy | CDN edge nodes | Mainframe |

The **air gap** between them is critical: the scale layer can ONLY communicate with the core via a message queue. It cannot directly read or write the truth store. This means:

- A compromised edge node cannot corrupt the core
- A DDoS on the scale layer doesn't affect core processing
- The core can be audited independently of scale behavior

---

## Get to Yes: Proving Correctness Before Production

### What "Yes" means

An artifact is at "Yes" when ALL of these are true:

1. **Authorized** — a policy rule explicitly permits this action
2. **Validated** — the output conforms to its schema (Pydantic)
3. **Approved** — a human approved it (or policy pre-approved the category)
4. **Traceable** — the full provenance chain is recorded in the truth store
5. **Bounded** — the action is within budget, rate limit, and scope

### How to Get to Yes

```
New artifact request arrives
         │
         ▼
┌─────────────────────┐
│ 1. SCHEMA VALIDATE  │ ← Does the input conform to expected shape?
│    (Pydantic)       │    If no → REJECT (never process malformed input)
└──────────┬──────────┘
           │ valid
           ▼
┌─────────────────────┐
│ 2. POLICY CHECK     │ ← Is this action permitted by Cedar rules?
│    (pre-execution)  │    If no → DENY + log denial reason
└──────────┬──────────┘
           │ permitted
           ▼
┌─────────────────────┐
│ 3. BUDGET CHECK     │ ← Is the agent within its daily token budget?
│    (token budget)   │    If no → QUEUE for tomorrow
└──────────┬──────────┘
           │ within budget
           ▼
┌─────────────────────┐
│ 4. DEDUP CHECK      │ ← Have we already processed this exact input?
│    (cache + RAG)    │    If yes → return cached result (zero cost)
└──────────┬──────────┘
           │ not duplicate
           ▼
┌─────────────────────┐
│ 5. EXECUTE          │ ← Call LLM, produce artifact
│    (agent engine)   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 6. OUTPUT VALIDATE  │ ← Does the output conform to expected schema?
│    (instructor)     │    If no → RETRY (up to 3x) then FAIL
└──────────┬──────────┘
           │ valid output
           ▼
┌─────────────────────┐
│ 7. POLICY CHECK     │ ← Is the OUTPUT permitted? (no PII, no secrets,
│    (post-execution) │    no forbidden content in the artifact)
└──────────┬──────────┘
           │ permitted
           ▼
┌─────────────────────┐
│ 8. APPROVAL GATE    │ ← Does this need human approval?
│    (auto-approve    │    If auto-approved → execute immediately
│     or queue)       │    If not → queue for human review
└──────────┬──────────┘
           │ approved
           ▼
┌─────────────────────┐
│ 9. RECORD TRUTH     │ ← Write to append-only ledger:
│    (truth store)    │    who, what, when, why, how, hash
└──────────┬──────────┘
           │
           ▼
        ✅ YES
```

Every artifact that reaches "Yes" has passed 9 gates. Every gate is logged. Every denial is logged. The system can prove, at any point in time, exactly how any artifact reached its current state.

---

## Stay at Yes: Maintaining Correctness Under Load

### The Quantity Problem

At 2 million users, you might process:
- 50,000 emails/day classified
- 10,000 community posts moderated
- 5,000 drafts generated
- 1,000 approvals processed

The temptation is to cut corners for speed. **Don't.**

### Patterns for Staying at Yes

**Pattern 1: Immutable artifacts**
Once an artifact reaches "Yes" and is published, it's never modified. If it needs to change, a NEW version is created with its own provenance chain. The old version remains in the truth store forever.

**Pattern 2: Continuous validation**
Every hour, a background process re-validates a random sample of recent artifacts against current policies. If any fail (because a policy was updated), they're flagged for review. This catches drift.

**Pattern 3: Monotonic timestamps**
The truth store uses monotonic timestamps (not wall clock). Events are ordered by sequence number, not time. This prevents clock-skew attacks and ensures causal ordering.

**Pattern 4: Quorum writes**
For the truth store, a write is only acknowledged when it's been replicated to at least 2 nodes. This prevents split-brain scenarios where two nodes disagree on truth.

**Pattern 5: Read-your-writes consistency**
After Bob approves an item, his next read MUST see that approval. The scale layer routes his subsequent requests to the same core node until replication catches up.

---

## Recover to Yes: When Things Break

### Failure taxonomy

| Failure | Detection | Recovery |
|---------|-----------|----------|
| Edge node crash | Health check (5s) | Auto-replace (Fly.io) |
| LLM API down | Timeout (10s) | Fallback model → queue if all fail |
| Database unreachable | Connection timeout (3s) | Retry → read replica → alert |
| Policy file corrupted | Checksum mismatch | Revert to last signed version |
| Agent produces bad output | Post-execution policy check | Reject + retry + alert |
| Operator account compromised | Anomaly detection (unusual approvals) | Lock account + alert other operator |
| Truth store corruption | Checksum on every read | Restore from continuous backup (PITR) |
| Budget exceeded | Pre-execution check | Queue for tomorrow + alert |

### Recovery principles

1. **Never lose data** — the truth store has continuous backup. Worst case: restore to 1 second ago.
2. **Never serve stale** — if the core is recovering, the scale layer returns "service degraded" rather than serving cached (potentially wrong) data.
3. **Never auto-fix silently** — every recovery action is logged. Bob sees what happened and why.
4. **Prefer availability over correctness for reads, correctness over availability for writes** — you can always re-read, but a bad write is permanent.

### The Recovery Sequence

```
Failure detected
       │
       ▼
┌─────────────────────┐
│ 1. ISOLATE           │ ← Stop the failing component from affecting others
│    (circuit breaker) │    Suspend the agent, close the connection, etc.
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 2. ALERT            │ ← Notify Bob via ALL channels (Telegram + SMS + push)
│    (multi-channel)  │    Include: what failed, when, impact, suggested action
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 3. DIAGNOSE         │ ← Auto-analyze: check last 10 audit entries for the
│    (self-diagnose)  │    failing component. Identify the root cause pattern.
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 4. RECOVER          │ ← Apply the appropriate recovery:
│    (auto or manual) │    - Retry (transient failure)
│                     │    - Fallback (model unavailable)
│                     │    - Restore (data corruption)
│                     │    - Escalate (unknown failure)
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 5. VERIFY           │ ← Run the "Get to Yes" sequence on a test artifact
│    (smoke test)     │    If it passes → component is recovered
│                     │    If it fails → escalate to manual intervention
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 6. RESUME           │ ← Re-enable the component
│    (gradual)        │    Process queued items (oldest first)
│                     │    Monitor for 5 minutes before declaring healthy
└──────────┬──────────┘
           │
           ▼
        ✅ BACK TO YES
```

---

## The Free Tier Design

### Principle: Free users get the same correctness guarantees, just less throughput.

| Dimension | Free | Pro ($29/mo) | Enterprise |
|-----------|------|-------------|-----------|
| Agents | 2 | 10 | Unlimited |
| Actions/month | 500 | 10,000 | Unlimited |
| LLM model | Groq only (free) | Groq + GPT-4o | Any model |
| Channels | Telegram only | All channels | All + custom |
| Audit retention | 7 days | 90 days | Forever |
| Policy rules | 5 | Unlimited | Unlimited |
| Support | Community | Email | Dedicated |
| SLA | Best effort | 99.5% | 99.9% |

**Critical:** Free tier runs on the SAME core infrastructure. Same truth store. Same policy engine. Same correctness guarantees. The only difference is throughput limits and feature gates.

This means:
- A free user's artifacts are just as trustworthy as an enterprise user's
- Upgrading doesn't require migration (same database, same policies)
- The core never knows or cares about tiers (that's the scale layer's job)

### How free scales to 2 million

At 2M users on free tier (500 actions/month each):
- 1 billion actions/month total
- But: 80% are auto-approved (no human review needed)
- And: 60% hit the cache (no LLM call needed)
- Real LLM calls: ~200M/month
- At Groq pricing ($0.59/M tokens): ~$120/month for ALL free users

The math works because:
1. Classification is cheap (Groq, cached)
2. Most actions are repetitive (cache hit)
3. Free tier uses the cheapest model only
4. The core is fixed-cost (doesn't scale with users)

---

## Quality Control for AI Artifacts

### The problem

GenAI produces artifacts (emails, posts, reports) that LOOK correct but might be:
- Hallucinated (facts that aren't true)
- Off-voice (doesn't match the org's tone)
- Leaking PII (accidentally includes personal data)
- Biased (unfair treatment of certain groups)
- Stale (based on outdated information)

### The AIGovOps quality framework

Every artifact is scored on 5 dimensions before reaching "Yes":

```
┌─────────────────────────────────────────────────────┐
│              ARTIFACT QUALITY SCORECARD               │
│                                                       │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐  │
│  │ACCURACY │ │ VOICE   │ │ SAFETY  │ │FRESHNESS│  │
│  │         │ │         │ │         │ │         │  │
│  │ Facts   │ │ Tone    │ │ No PII  │ │ Current │  │
│  │ correct?│ │ matches?│ │ No bias │ │ info?   │  │
│  │         │ │         │ │ No harm │ │         │  │
│  │ ██████░ │ │ ████████│ │ ████████│ │ █████░░ │  │
│  │  85%    │ │  98%    │ │  100%   │ │  75%    │  │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘  │
│                                                       │
│  ┌─────────┐                                         │
│  │AUTHORITY│  Overall: ✅ PASS (min threshold: 70%)  │
│  │         │                                         │
│  │ Approved│  Policy: agents/email.cedar:line 12     │
│  │ by whom?│  Approved by: bob (2026-05-16 08:30)    │
│  │         │                                         │
│  │ ████████│                                         │
│  │  100%   │                                         │
│  └─────────┘                                         │
└─────────────────────────────────────────────────────┘
```

### How scoring works

1. **Accuracy** — cross-reference claims against RAG index + live search. Flag unverifiable claims.
2. **Voice** — compare against the org's voice rules (no superlatives, practitioner-first, etc.)
3. **Safety** — scan for PII, secrets, harmful content, bias indicators
4. **Freshness** — check if referenced information is current (not outdated)
5. **Authority** — verify the approval chain is complete and valid

Artifacts below the threshold (configurable, default 70% on any dimension) are held for human review regardless of auto-approve rules.

---

## Visual Storytelling: How We Built This

### The narrative arc

```
Episode 1: "The Problem"
  → Two people trying to run a foundation. Drowning in email, community, content.
  → Visual: Split-screen of Bob's inbox (80 emails) vs. his actual mission work.

Episode 2: "The Idea"
  → What if AI agents did the admin work? But with governance built in.
  → Visual: Agent cards appearing, each handling one domain.

Episode 3: "Get to Yes"
  → Building the 9-gate pipeline. Every artifact proven correct before it ships.
  → Visual: Animated pipeline with gates opening/closing.

Episode 4: "Stay at Yes"
  → Running at scale without cutting corners. The mainframe-like core.
  → Visual: Two-layer architecture diagram, core glowing steady while edges scale.

Episode 5: "Recover to Yes"
  → When things break (and they will). The 6-step recovery sequence.
  → Visual: Red alert → isolate → diagnose → recover → verify → green.

Episode 6: "The Result"
  → Bob's daily interaction: 5 minutes. 8 agents. Zero hires.
  → Visual: Before/after comparison. Time saved. Quality maintained.
```

### Content formats

| Format | Platform | Length | Purpose |
|--------|----------|--------|---------|
| Animated explainer | YouTube, site | 3 min | "What is this?" for newcomers |
| Tutorial series | YouTube | 5-10 min each | "How to set it up" step by step |
| Architecture deep-dive | YouTube, blog | 15 min | For technical practitioners |
| Daily "agent diary" | Twitter/X, LinkedIn | 30 sec | "Here's what my agents did today" |
| Live demo | Loom, embedded on site | 5 min | Interactive walkthrough |
| Avatar-narrated shorts | TikTok, Reels, Shorts | 60 sec | Viral-format explanations |

### Avatar approach

Use AI-generated avatars (HeyGen, Synthesia, or D-ID) to narrate:
- **"Bob"** avatar explains the operator perspective
- **"Agent"** avatar (robot-styled) explains what the agents do
- **"Auditor"** avatar explains the governance layer

Each video ends with: "Built with the AIGovOps Framework. Try it: `pip install aigovops-agent-framework`"

---

## The AIGovOps Certification Mark

Organizations that implement this architecture can display:

```
┌──────────────────────────────────────┐
│  ✅ AIGovOps Foundation Certified     │
│                                       │
│  Get to Yes  ·  Stay at Yes  ·       │
│  Recover to Yes                       │
│                                       │
│  Audit trail: immutable               │
│  Policy: code-enforced                │
│  Human-in-the-loop: verified          │
│                                       │
│  Certified: 2026-05-16                │
│  Valid through: 2027-05-16            │
└──────────────────────────────────────┘
```

Certification requires:
1. All 9 gates implemented and tested
2. Append-only audit log with no gaps
3. Policy-as-code with version control
4. Human approval for all external communications
5. Recovery procedure documented and tested
6. Continuous validation running

---

## Implementation Roadmap

| Phase | What | When | Cost |
|-------|------|------|------|
| 1 | Deploy current system to Fly.io + Neon | This week | $5/mo |
| 2 | Add OAuth2 + tenant isolation | Next week | +$0 |
| 3 | Implement 9-gate pipeline formally | Week 3 | +$0 |
| 4 | Add quality scorecard | Week 4 | +$0 |
| 5 | Open to 5 beta community members | Month 2 | +$0 |
| 6 | Create video content (3 episodes) | Month 2 | $100 (avatar tool) |
| 7 | Launch certification program | Month 3 | +$0 |
| 8 | Scale to 50 orgs | Month 4 | +$50/mo infra |
| 9 | Revenue covers costs | Month 5 | Break-even at 4 Pro customers |

---

## Summary

The "Get to Yes, Stay at Yes, Recover to Yes" architecture is:

1. **A design philosophy** — every artifact must be provably correct
2. **A technical architecture** — two layers (scale + core) with an air gap
3. **A quality framework** — 5-dimension scoring for AI artifacts
4. **A certification standard** — organizations can prove they govern AI responsibly
5. **A story** — told through video, tutorials, and live demos

It starts with two people and scales to two million because the core never changes. It just processes more messages from the queue. The correctness guarantees are the same at any scale.

That's the AIGovOps promise: **Ship AI. Steady AI. Recover AI.**
