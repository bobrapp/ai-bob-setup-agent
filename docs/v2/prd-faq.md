# PRD-FAQ (Amazon Working Backwards Format)

## AIGovOps Foundation Automation System v2

---

## Press Release

**FOR IMMEDIATE RELEASE**

**AIGovOps Foundation Ships Open-Source "AI Team" That Lets Two People Run a Nonprofit at Scale**

*Portland, OR — May 2026*

The AIGovOps Foundation today released v2 of its internal automation system — an open-source platform that replaces a 5-person operations team with 8 AI agents, all governed by policy-as-code and human-in-the-loop approval.

Co-founders Bob Rapp and Ken Johnston built the system to prove their own thesis: that AI governance isn't just theory — it's operational practice. The system classifies emails, welcomes community members, moderates content, drafts newsletters, tracks tasks, and manages outreach — all while logging every action to an immutable audit trail.

"We built this because we needed it," said Rapp. "But we also built it to show that you can run AI agents responsibly. Every agent has explicit policies about what it can and can't do. Every action is logged. Nothing goes out without a human tap."

The system is available at github.com/bobrapp/ai-bob-setup-agent under MIT license.

---

## FAQ

### Q: Who is this for?

**A:** Primarily Bob and Ken — two co-founders running the AIGovOps Foundation. Secondarily, any small team (1-5 people) that wants to operate at scale without hiring, while maintaining governance and audit trails.

### Q: Why not just hire a virtual assistant?

**A:** Three reasons: (1) A VA can't work 24/7 and respond in 5 minutes to a new member join at 2 AM. (2) A VA doesn't produce an immutable audit log of every action. (3) A VA costs $3-5K/month for the coverage we need. This system costs ~$50/month in API fees.

### Q: Can the agents send emails or post without permission?

**A:** No. Every external communication passes through the Approval Queue. Bob or Ken must explicitly approve via Telegram, web, or voice before anything goes out. This is enforced by Cedar policy, not just code convention.

### Q: What happens if an agent makes a mistake?

**A:** Three layers of protection: (1) Nothing sends without approval. (2) If an agent's failure rate exceeds 10% in 24 hours, it's automatically suspended. (3) Every action is logged — you can see exactly what happened and why.

### Q: How is this different from the customer-facing ai-bob-setup-agent?

**A:** The customer product provisions Hermes/OpenClaw agents on Orgo for paying clients. This internal system automates Bob and Ken's own work. Different code paths, different config, different purpose. They share an audit log format and the AIGovOps provenance rule.

### Q: What about privacy?

**A:** The audit log never stores email bodies, post content, or personal information. Only metadata: subject lines, member IDs (not names), action summaries. API keys are stored in the system keychain, never in files. The SQLite database is encrypted at rest.

### Q: What if Groq or OpenAI goes down?

**A:** The system has automatic fallback: Groq → OpenAI → local model (if configured). If all models are unavailable, agents queue their intended actions and retry when service returns. No data is lost.

### Q: Can I add new agents without writing code?

**A:** Yes. In v2, agents are YAML definitions. You write a config file describing the trigger, model, prompt, output schema, and actions. The runtime engine executes it. No Python required.

### Q: How does voice work?

**A:** Five voice commands via Siri Shortcuts (or Alexa Skills) that hit the API: "What's pending?", "Approve all low-risk", "Suspend [agent]", "What did my agents do today?", "Draft a post about [topic]". Command-based, not conversational.

### Q: What's the total cost?

**A:** ~$50-250/month depending on services chosen. Minimum viable: Telegram (free) + Groq (free) + OpenAI ($10-20) = ~$20/month. Full stack with Circle.so: ~$250/month. Compare to a part-time VA at $2-4K/month.

### Q: Is this production-ready?

**A:** v1 (current) is functional and ships tonight. v2 (this document) adds persistence, multi-interface, and policy-as-code over the following 5 weeks. The system is designed to be used while being improved.
