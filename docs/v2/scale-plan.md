# Scale Plan

## Current State (v1 — 2 operators)

| Dimension | Current | Limit |
|-----------|---------|-------|
| Operators | 2 (Bob + Ken) | 2 |
| Agents | 8 | ~15 before complexity hurts |
| Events/day | ~200 (emails + posts + schedules) | ~5,000 (SQLite handles easily) |
| LLM calls/day | ~100-300 | ~10,000 (API rate limits) |
| Approval items/day | ~10-30 | ~100 (human bottleneck) |
| Storage | <100MB (SQLite) | 10GB+ before performance degrades |
| Cost | ~$50-250/month | Budget-constrained |

---

## Scale Phases

### Phase 1: Solo Foundation (Now — Month 1)
**Users:** Bob + Ken
**Load:** 200 events/day, 100 LLM calls/day
**Infra:** Single process on MacBook or VPS

No scaling needed. SQLite handles this trivially. Focus on reliability and UX.

### Phase 2: Active Foundation (Month 2-3)
**Users:** Bob + Ken + 3-5 community moderators (read-only audit access)
**Load:** 500 events/day, 300 LLM calls/day
**Infra:** Same single process

Changes needed:
- Add read-only JWT role for community moderators
- Add `/api/audit` endpoint with role-based filtering
- Consider moving to a $20/mo VPS for always-on availability

### Phase 3: Framework Adoption (Month 4-6)
**Users:** 5-25 other organizations running their own instances
**Load:** Each instance independent (not multi-tenant)
**Infra:** Each org runs their own instance

Changes needed:
- Extract `aigovops-agent-framework` as a standalone PyPI package
- Provide `cookiecutter` template for new instances
- Documentation for self-hosting
- Optional: hosted version for non-technical users ($50/mo SaaS)

### Phase 4: Multi-Tenant SaaS (Month 6-12, if demand warrants)
**Users:** 50-200 organizations on a shared platform
**Load:** 50K events/day, 10K LLM calls/day
**Infra:** Requires architectural changes

Changes needed:
- Replace SQLite with PostgreSQL (multi-tenant)
- Add tenant isolation (row-level security)
- Move to container deployment (Docker + fly.io or Railway)
- Add billing (Stripe)
- Add onboarding wizard (web-based, no CLI)
- Add usage metering and cost allocation per tenant

---

## Scaling Decisions (When to Change What)

| Trigger | Action | Effort |
|---------|--------|--------|
| >1000 events/day | Add event batching (process in groups of 10) | 2 hours |
| >500 LLM calls/day | Add response caching (1h TTL for identical prompts) | 4 hours |
| >50 approval items/day | Add priority levels + auto-approve for low-risk | 1 day |
| >5 operators | Move from JWT to proper auth (OAuth2 / Auth0) | 2 days |
| >10GB database | Archive old events/audit entries to cold storage | 4 hours |
| Need 99.9% uptime | Move to VPS with systemd + health monitoring | 1 day |
| Multi-tenant demand | PostgreSQL migration + tenant isolation | 2 weeks |

---

## Cost Scaling

| Scale | LLM cost | Infra cost | Total |
|-------|----------|-----------|-------|
| 2 operators, 100 calls/day | $10-20/mo | $0-20/mo | $20-40/mo |
| 2 operators, 500 calls/day | $30-50/mo | $20/mo | $50-70/mo |
| 10 operators (framework) | Each pays own LLM | Each pays own infra | $50-100/mo each |
| 50 tenants (SaaS) | $500-1000/mo (shared) | $100-200/mo | Revenue: $2500-5000/mo |

### Cost Optimization Levers

1. **Groq for classification** — 10x cheaper than OpenAI for 80% of calls
2. **Response caching** — identical emails from same sender = cached classification
3. **Batch processing** — group events and process together (fewer LLM round-trips)
4. **Model downsizing** — use GPT-4o-mini instead of GPT-4o for routine drafts
5. **Local models** — Ollama for classification if Groq goes down or costs increase

---

## Performance Targets

| Operation | Target latency | Current |
|-----------|---------------|---------|
| Email classification | <2s | ~0.8s (Groq) |
| Draft reply | <5s | ~3s (GPT-4o) |
| Welcome DM generation | <3s | ~2s (GPT-4o) |
| Post moderation | <2s | ~0.8s (Groq) |
| Approval queue presentation | <1s | <0.5s |
| Audit log write | <50ms | <10ms (SQLite) |
| Event processing | <100ms | <20ms (SQLite polling) |
| API response (read) | <200ms | <50ms |

---

## Reliability Targets

| Metric | Target | How |
|--------|--------|-----|
| Uptime | 99% (7h downtime/month OK) | systemd auto-restart |
| Data durability | Zero loss | SQLite WAL mode + 6h backups |
| Event delivery | At-least-once | Unprocessed events replayed on restart |
| Approval delivery | Within 30s | WebSocket + Telegram push |
| Recovery time | <5 minutes | systemd restart + event replay |

---

## What We Explicitly Won't Scale

1. **Won't build a general-purpose agent platform** — this is for small teams running their own operations
2. **Won't support real-time voice conversation** — voice is command-based only
3. **Won't support >200 tenants** — if demand exceeds that, partner with an infra company
4. **Won't replace human judgment** — agents draft, humans decide. That's the product.
5. **Won't compete with enterprise GRC tools** — we're for practitioners, not compliance departments
