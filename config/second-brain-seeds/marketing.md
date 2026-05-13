# Second Brain Seed — Marketing Vertical
#
# This file bootstraps the Obsidian vault for a marketing customer.
# The HermesInstaller uploads it during onboarding (step 5: load_second_brain).
# It creates the initial directory structure and starter files.
#
# After seeding, the agent reads from and writes to this vault continuously,
# building institutional memory over time.

## Vault Structure

The seed creates these directories on the cloud computer at `/data/obsidian/`:

```
/data/obsidian/
├── company/
│   ├── profile.md           ← customer overview (fill in during onboarding)
│   ├── brand-guidelines.md  ← tone, voice, visual identity
│   ├── competitors.md       ← known competitors and positioning
│   └── org-chart.md         ← key contacts and decision-makers
├── personas/
│   ├── README.md            ← how to define ICPs
│   └── example-icp.md      ← template ideal customer profile
├── templates/
│   ├── outreach/
│   │   ├── cold-intro.md    ← first-touch cold email
│   │   ├── follow-up-1.md   ← 3-day follow-up
│   │   ├── follow-up-2.md   ← 7-day follow-up
│   │   ├── follow-up-3.md   ← 14-day breakup email
│   │   └── warm-intro.md    ← mutual connection intro
│   ├── proposals/
│   │   └── standard.md      ← proposal structure template
│   └── content/
│       ├── blog-post.md     ← blog post outline
│       └── social-post.md   ← social media format
├── meetings/
│   └── README.md            ← meeting notes land here (from Granola)
├── playbooks/
│   ├── outreach-cadence.md  ← standard outreach sequence
│   ├── qualification.md     ← BANT/MEDDIC qualification criteria
│   └── objection-handling.md ← common objections + responses
├── history/
│   ├── campaigns/
│   │   └── README.md        ← campaign performance logs
│   └── conversations/
│       └── README.md        ← notable prospect interactions
├── discoveries/
│   ├── prospects/
│   │   └── README.md        ← prospect research notes
│   └── market/
│       └── README.md        ← market trend observations
├── drafts/
│   ├── emails/
│   │   └── README.md        ← outreach drafts pending review
│   └── content/
│       └── README.md        ← content drafts pending approval
└── logs/
    └── README.md            ← daily activity summaries
```

---

## Starter Files

### company/profile.md

```markdown
# Company Profile

- **Legal name:** [fill in]
- **Website:** [fill in]
- **Industry:** [fill in]
- **Size:** [fill in]
- **Founded:** [fill in]

## What they do
[One-paragraph description of the customer's business]

## Key pain points
- [Pain point 1]
- [Pain point 2]
- [Pain point 3]

## Why they hired us
[What outcome they're paying for]

## Key metrics they care about
- [Metric 1]
- [Metric 2]
```

### personas/example-icp.md

```markdown
# Ideal Customer Profile: [Title]

## Demographics
- Title: [e.g., VP Marketing, CMO, Head of Growth]
- Company size: [e.g., 50-500 employees]
- Industry: [e.g., B2B SaaS]
- Geography: [e.g., North America]

## Pain points
- [What keeps them up at night]
- [What they've tried that hasn't worked]
- [What they wish they had]

## Triggers (when they're ready to buy)
- [Trigger event 1: e.g., new funding round]
- [Trigger event 2: e.g., hired new sales team]
- [Trigger event 3: e.g., competitor launched similar product]

## Messaging that resonates
- Lead with: [value proposition]
- Avoid: [common turn-offs]
- Social proof: [type of case study that works]
```

### templates/outreach/cold-intro.md

```markdown
# Cold Intro Template

Subject: {{SUBJECT_LINE}}

Hi {{FIRST_NAME}},

{{PERSONALIZED_OPENING — reference something specific about them or their company}}

{{VALUE_PROPOSITION — one sentence on what you can do for them}}

{{SOCIAL_PROOF — one sentence, ideally with a number}}

Would it make sense to grab 15 minutes this week to see if there's a fit?

Best,
{{SENDER_NAME}}

---
Notes:
- Keep under 150 words
- Personalized opening must reference a REAL fact (check Perplexity)
- Never use "just reaching out" or "hope you're well"
- Subject line should be 3-6 words, no clickbait
```

### playbooks/outreach-cadence.md

```markdown
# Outreach Cadence

## Standard sequence (14 days)

| Day | Action | Template | Channel |
|-----|--------|----------|---------|
| 0   | Cold intro | `cold-intro.md` | Email |
| 3   | Follow-up 1 | `follow-up-1.md` | Email |
| 5   | Social touch | — | LinkedIn (via Composio if available) |
| 7   | Follow-up 2 | `follow-up-2.md` | Email |
| 10  | Value add | Share relevant content | Email |
| 14  | Breakup | `follow-up-3.md` | Email |

## Rules
- Max 25 new outreach emails per day (deliverability)
- No outreach on weekends
- If prospect replies at any point, exit sequence and handle personally
- If prospect opens 3+ times without replying, escalate to operator
- Log every send to HubSpot via Composio
```

### playbooks/qualification.md

```markdown
# Lead Qualification — BANT Framework

## Budget
- Can they afford our service? (min: $5K/mo for OpenClaw tier)
- Who controls the budget?
- When does their budget cycle reset?

## Authority
- Is this the decision-maker?
- Who else needs to sign off?
- What's their buying process?

## Need
- What specific problem are they solving?
- How are they solving it today?
- What happens if they don't solve it?

## Timeline
- When do they need a solution by?
- What's driving the urgency?
- Are they evaluating alternatives?

## Scoring
- 4/4 BANT = Hot (schedule demo immediately)
- 3/4 BANT = Warm (nurture with content)
- 2/4 BANT = Cool (add to long-term drip)
- 1/4 BANT = Cold (don't pursue actively)
```

---

## Seeding Instructions

The `HermesInstaller.load_second_brain()` action should:

1. Create the directory structure above on the cloud computer
2. Write the starter files with placeholder content
3. Set file permissions so the agent runtime can read and write
4. Log the seed operation to `logs/seed-{date}.md`

The operator then fills in `company/profile.md` and `personas/` during onboarding.
As the agent works, it populates `discoveries/`, `drafts/`, `history/`, and `logs/`
automatically — building institutional memory that compounds over time.
