# Context Templates (agents.mmd)

Each agent boots with a `.mmd` context file — a Markdown briefing document loaded into
the agent's working memory. It tells the agent who it is, what tools it has, and how
to behave.

## Templates

| Template | Vertical | Best for |
|----------|----------|----------|
| `agents.mmd.template` | Generic | Any vertical — start here and customize |
| `marketing.mmd.template` | Marketing | Outreach, content, lead-gen agents |

## How to use

1. Pick the closest vertical template (or start with the generic one)
2. Copy it to the customer's config directory:
   ```
   mkdir -p config/customers/<slug>/
   cp config/context-templates/marketing.mmd.template config/customers/<slug>/<agent-name>.mmd
   ```
3. Replace all `{{PLACEHOLDERS}}` with real values
4. Reference the file in the customer YAML:
   ```yaml
   second_brain:
     enabled: true
     seed_path: "config/second-brain-seeds/marketing.md"
     context_file: "config/customers/<slug>/<agent-name>.mmd"
   ```
5. Run onboarding — the installer uploads the context file to the cloud computer

## Adding vertical templates

Create a new `<vertical>.mmd.template` in this directory. Follow the 6-section structure:

1. **Identity** — who the agent is and who it works for
2. **Second Brain** — Obsidian vault paths (read-from and write-to)
3. **Tools** — MCPs, Composio apps, Agent Mail
4. **Behavioral Guidelines** — tone, quality standards, escalation rules
5. **Schedule & Routines** — daily and weekly automated tasks
6. **Operator Notes** — private context not shared with the customer
