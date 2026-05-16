# Product Requirements Document (PRD)

## AIGovOps Foundation — Personal + Foundation Automation System v2

**Version:** 2.0.0
**Date:** 2026-05-15
**Authors:** Bob Rapp, Ken Johnston
**Status:** Draft

---

## 1. Executive Summary

Two co-founders (Bob and Ken) need to run a nonprofit foundation, a community of practitioners, a weekly newsletter, an outreach pipeline, and their personal professional work — at the scale of a 5-person team — without hiring anyone.

The system uses AI agents to handle administrative, content, community, and research work. Every consequential action requires human approval. Every action is logged. The system is the Foundation's own proof-of-concept for "AI governance in practice."

---

## 2. Problem Statement

| Pain | Current state | Desired state |
|------|--------------|---------------|
| Email overwhelm | Bob processes 80+ emails/day manually | Agent triages, drafts replies; Bob reviews 5-10 |
| Community management | New members wait days for welcome | Welcomed within 5 minutes, automatically |
| Content creation | Newsletter takes 4+ hours/week | Agent assembles draft; Bob edits 30 min |
| Research tracking | Miss important publications | Daily digest of relevant items by 8 AM |
| Task follow-through | Action items from meetings get lost | Auto-created in Asana within 30 min of meeting end |
| Outreach | Contacts fall through cracks | 7-day auto follow-up with approval |
| Governance | No audit trail of what agents do | Every action logged with provenance |

---

## 3. Users

| User | Role | Interaction mode |
|------|------|-----------------|
| Bob Rapp | Primary operator, co-founder | Web, Telegram, Voice |
| Ken Johnston | Secondary operator, co-founder | Web, Telegram |
| Community members | Passive recipients | Receive DMs, see posts |
| Auditors | Read-only | Web audit viewer |

---

## 4. Requirements

### 4.1 Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| F1 | Classify incoming emails into 5 categories with >85% accuracy | P0 |
| F2 | Draft replies for action-required emails | P0 |
| F3 | Welcome new community members within 5 minutes | P0 |
| F4 | Classify community posts for spam/toxicity/PII/off-topic | P0 |
| F5 | Produce daily research digest by 8 AM Pacific | P1 |
| F6 | Assemble weekly newsletter draft by Sunday 6 PM | P1 |
| F7 | Extract meeting action items → Asana tasks | P1 |
| F8 | Track outreach pipeline with 7-day auto follow-up | P1 |
| F9 | Generate weekly governance report | P1 |
| F10 | Support web, mobile, Telegram, and voice interfaces | P2 |

### 4.2 Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NF1 | Approval queue item presented within 30 seconds of generation | <30s |
| NF2 | No data loss on process restart | Zero loss |
| NF3 | Audit log append-only, tamper-evident | Immutable |
| NF4 | All external comms require logged approval | 100% |
| NF5 | Agent failure auto-suspension at >10% failure rate | <60s detection |
| NF6 | System operational cost | <$250/month |
| NF7 | Cold start to first approval item | <5 minutes |
| NF8 | Support 2 concurrent operators | Bob + Ken |

### 4.3 Constraints

- Must run on a single machine (Bob's MacBook or a $20/mo VPS)
- Must not require DevOps expertise to operate
- Must follow AIGovOps Foundation provenance rule
- Must not store email bodies or post content in logs (metadata only)
- Must work without internet for cached/queued operations (graceful degradation)

---

## 5. Success Metrics

| Metric | Baseline (manual) | Target (automated) |
|--------|-------------------|-------------------|
| Bob's email processing time | 2 hours/day | 15 min/day |
| New member welcome time | 1-3 days | <5 minutes |
| Newsletter creation time | 4 hours/week | 30 min/week (review only) |
| Missed outreach follow-ups | ~40% | 0% |
| Agent actions without audit trail | 100% | 0% |

---

## 6. Out of Scope (v2)

- Billing/invoicing automation
- Customer-facing agent provisioning (that's the separate ai-bob-setup-agent product)
- Multi-tenant support (this is Bob + Ken only)
- Real-time voice conversation (voice is command-based, not conversational)
