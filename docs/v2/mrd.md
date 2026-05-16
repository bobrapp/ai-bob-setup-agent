# Market Requirements Document (MRD)

## AIGovOps Foundation Automation — Market Context

---

## 1. Market Opportunity

### The problem space
- 78% of nonprofits have fewer than 5 full-time staff (NCCS 2025)
- Average nonprofit founder spends 60% of time on admin, not mission
- AI agent tools exist but lack governance, audit trails, and policy enforcement
- No open-source solution combines agent automation with policy-as-code

### The gap
| What exists | What's missing |
|-------------|---------------|
| ChatGPT, Claude (general AI) | No workflow automation, no audit trail |
| Zapier, Make.com (automation) | No AI reasoning, no approval queues |
| Marblism, Sintra (AI agents) | No audit export, no policy-as-code |
| n8n (open-source automation) | No built-in AI governance layer |

### Our position
The AIGovOps Foundation automation system is the first open-source platform that combines:
1. AI agent automation (LLM-powered)
2. Policy-as-code governance (Cedar)
3. Human-in-the-loop approval
4. Immutable audit trail
5. Multi-interface (web, mobile, voice, Telegram)

---

## 2. Target Users

### Primary: Small nonprofit teams (1-5 people)
- Running communities, newsletters, outreach
- Can't afford to hire but need to scale
- Care about governance and transparency
- Technically comfortable (can run a Python script)

### Secondary: Solo operators / solopreneurs
- Running a business or practice alone
- Need email triage, task management, content creation
- Want audit trails for compliance or client reporting

### Tertiary: AI governance practitioners
- Want to see policy-as-code in action
- Looking for reference implementations
- May adopt the framework for their own organizations

---

## 3. Competitive Landscape

| Solution | AI Agents | Policy-as-Code | Audit Trail | Open Source | Cost |
|----------|-----------|----------------|-------------|-------------|------|
| **This system** | ✅ 8 agents | ✅ Cedar | ✅ Immutable JSONL | ✅ MIT | ~$50/mo |
| Zapier + AI | ⚠️ Basic | ❌ | ⚠️ Logs only | ❌ | $50-200/mo |
| Make.com + AI | ⚠️ Basic | ❌ | ⚠️ Logs only | ❌ | $12-50/mo |
| n8n | ⚠️ Via plugins | ❌ | ⚠️ Basic | ✅ | Free-$50/mo |
| Marblism | ✅ | ❌ | ❌ No export | ❌ | $100+/mo |
| Sintra | ✅ | ❌ | ❌ No export | ❌ | $100+/mo |
| Custom (hire devs) | ✅ | ✅ | ✅ | Depends | $5-20K/mo |

---

## 4. Differentiation

### Why this wins for our target user:

1. **Open source** — no vendor lock-in, inspect everything, fork and modify
2. **Policy-as-code** — governance isn't a feature, it's the architecture
3. **Audit-first** — every action logged before it executes, not after
4. **Human-in-the-loop** — agents draft, humans decide (not the other way around)
5. **Cost** — $50/mo vs. $3-5K/mo for a VA or $5-20K/mo for custom dev
6. **Dogfooding** — we use it ourselves, daily, in production

---

## 5. Go-to-Market

### Phase 1: Internal use (now)
- Bob and Ken use it daily
- Prove it works at scale of 2 operators
- Document everything (HIBT rule)

### Phase 2: Community showcase (Month 2)
- Present at AIGovOps Foundation community events
- Publish case study: "How 2 people run a foundation with 8 AI agents"
- Open-source the full system (already MIT licensed)

### Phase 3: Framework adoption (Month 3-6)
- Extract the agent runtime + policy engine as a standalone framework
- Publish as `aigovops-agent-framework` on PyPI
- Other nonprofits and small teams adopt it
- Foundation grows through practitioners using the framework

### Phase 4: Consulting (Month 6+)
- Offer setup consulting for organizations that want the system but don't want to configure it themselves
- $2-5K one-time setup fee
- Ongoing support optional

---

## 6. Success Metrics (Market)

| Metric | 3-month target | 6-month target |
|--------|---------------|---------------|
| GitHub stars | 100 | 500 |
| Forks | 10 | 50 |
| Community members using it | 5 | 25 |
| Case studies published | 1 | 3 |
| Framework downloads (PyPI) | — | 200/month |
| Consulting engagements | — | 2 |
