# Voice Interface

## Overview

Five voice commands available via Siri Shortcuts and Alexa:

| Command | What it does |
|---------|-------------|
| "What's pending?" | Reads approval queue summary |
| "Approve all low-risk" | Batch-approves welcomer + research items |
| "Suspend [agent]" | Suspends an agent |
| "What did my agents do today?" | Daily activity summary |
| "Draft about [topic]" | Triggers the writing agent |

## Siri Shortcuts Setup

1. Open the Shortcuts app on your iPhone/iPad
2. Import each `.shortcut` file from `voice/siri/`
3. Or use the iCloud share links below

Each shortcut calls `POST /api/voice` on your server with a JWT token.

### Configuration

Before importing, set these variables in each shortcut:
- `API_URL`: Your server URL (e.g., `https://your-server.com`)
- `TOKEN`: Your JWT token (get from `/api/auth/login`)

## Alexa Skill Setup

1. Go to the Alexa Developer Console
2. Create a new skill using the interaction model in `voice/alexa/`
3. Deploy the Lambda handler
4. Link to your API server

## How it works

```
Voice command → Siri/Alexa → HTTP POST /api/voice → Framework → Response → Spoken
```

All voice commands go through the same `/api/voice` API endpoint.
The response includes a `speech` field that Siri/Alexa reads aloud.
