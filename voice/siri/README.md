# Siri Shortcuts

## Quick Install

Import these shortcuts on your iPhone/iPad. Each one calls your AIGovOps API.

## Setup (one-time)

1. Get your JWT token:
   ```
   curl -X POST https://YOUR_SERVER/api/auth/login \
     -H "Content-Type: application/json" \
     -d '{"username": "bob", "password": "YOUR_PASSWORD"}'
   ```
   Copy the `token` value.

2. In each shortcut, replace:
   - `YOUR_API_URL` → your server URL
   - `YOUR_TOKEN` → the JWT token from step 1

## Shortcuts

### 1. "What's pending?"
- Trigger: "Hey Siri, what's pending"
- Action: Reads count and summary of approval queue items
- File: whats_pending.json

### 2. "Approve all low-risk"
- Trigger: "Hey Siri, approve low risk"
- Action: Batch-approves items from welcomer + research agents
- File: approve_low_risk.json

### 3. "Suspend agent"
- Trigger: "Hey Siri, suspend email agent"
- Action: Suspends the named agent
- File: suspend_agent.json

### 4. "Daily summary"
- Trigger: "Hey Siri, agent summary"
- Action: Reads today's activity stats
- File: daily_summary.json

### 5. "Draft about..."
- Trigger: "Hey Siri, draft about AI governance trends"
- Action: Triggers writing agent, confirms draft is queued
- File: draft_content.json
