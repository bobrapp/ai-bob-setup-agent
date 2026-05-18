# AIGovOps Bot — User Guide for Bob & Ken

Welcome! This guide shows you how to use the bot on every channel and what each command does.

---

## Quick Start (2 minutes)

The bot works the same way on every channel. You type a command, it responds. Here are the channels:

| Channel | How to access |
|---------|--------------|
| **Telegram** | Message `@aigovops_bot` |
| **Web** | Open https://aigovops-automation.fly.dev/ |
| **WhatsApp** | Message the Twilio WhatsApp number |
| **SMS** | Text the Twilio phone number |
| **Email** | Send email with subject starting with `cmd:` |

---

## Commands Reference

| Command | What it does | Example |
|---------|-------------|---------|
| `draft about [topic]` | AI writes a LinkedIn post | `draft about AI governance trends` |
| `classify [email text]` | Classify an email | `classify From: jane@corp.com Subject: Meeting tomorrow` |
| `research` | Scan for AI governance news | `research` |
| `costs` | Show 7-day cost breakdown | `costs` |
| `status` | System health check | `status` |
| `audit` | Last 10 actions | `audit` |
| `pending` | Show items waiting for approval | `pending` |
| `approve [id]` | Approve a pending item | `approve a3f2b1c4` |
| `reject [id]` | Reject a pending item | `reject a3f2b1c4` |
| `help` | Show all commands | `help` |

---

## Channel Setup Guides

---

### 1. Telegram (already working for Bob)

#### For Ken:

1. Open Telegram on your phone
2. Search for `@aigovops_bot`
3. Tap **Start** or send `hi`
4. You'll get an "Access denied" message — that's expected
5. Tell Bob you messaged the bot
6. Bob will add your chat ID and redeploy (takes 2 minutes)
7. After that, you're in — all commands work

#### For Bob (adding Ken):

1. After Ken messages the bot, check the logs:
   ```
   fly logs -a aigovops-automation | grep "Access denied"
   ```
2. Copy Ken's chat ID (the number in the log)
3. Add it:
   ```
   fly secrets set -a aigovops-automation TELEGRAM_KEN_CHAT_ID="KEN_ID_HERE"
   ```
4. Redeploy:
   ```
   fly deploy -a aigovops-automation --ha=false --yes
   ```
5. Tell Ken to try again — he's in

#### Using Telegram:

- Type any command directly: `draft about responsible AI`
- On draft/classify results, tap the **✅ Approve** or **❌ Reject** buttons
- Use `/` prefix for slash commands: `/research`, `/costs`, `/status`

---

### 2. Web Interface (works now for both)

#### Setup:

No setup needed. Just open the URL.

#### Access:

1. Open your browser
2. Go to: **https://aigovops-automation.fly.dev/**
3. You'll see the command interface

#### Using the Web UI:

- Click any **quick button** at the top (Status, Costs, Audit, etc.)
- Or type a command in the text box and click **Send** (or press Enter)
- Pending approvals appear at the bottom with Approve/Reject buttons
- Works on phone browsers too — bookmark it for quick access

#### Tips:

- Add it to your phone's home screen (Safari: Share → Add to Home Screen)
- It refreshes the pending queue automatically after each command

---

### 3. WhatsApp

#### Setup (one-time, Bob does this):

1. Go to https://console.twilio.com and sign up (or log in)
2. In the left sidebar, click **Messaging → Try it out → Send a WhatsApp message**
3. Twilio will show you a sandbox number and a join code
4. On your phone, send the join code to the Twilio sandbox number on WhatsApp
   - It looks like: `join [two-words]` sent to `+1 415 523 8886`
5. In Twilio console, go to **Messaging → Settings → WhatsApp Sandbox**
6. Set the webhook URL to:
   ```
   https://aigovops-automation.fly.dev/webhook/twilio
   ```
   (Set this for "When a message comes in")
7. Add the Twilio secrets:
   ```
   fly secrets set -a aigovops-automation \
     TWILIO_ACCOUNT_SID="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" \
     TWILIO_AUTH_TOKEN="your_auth_token"
   ```

#### For Ken:

1. Bob sends you the Twilio sandbox join code
2. On WhatsApp, send that join code to the sandbox number
3. After joining, send any command: `status`, `help`, etc.
4. The bot replies in WhatsApp just like Telegram

#### Using WhatsApp:

- Send any command as a regular message: `draft about AI safety`
- The bot replies with the result
- To approve/reject, send: `approve a3f2b1c4` or `reject a3f2b1c4`
- Send `pending` to see what's waiting

#### Tips:

- WhatsApp sandbox sessions expire after 72 hours of inactivity — just resend the join code
- For a permanent WhatsApp number (no sandbox), upgrade to Twilio WhatsApp Business ($15/mo)

---

### 4. SMS

#### Setup (one-time, Bob does this):

1. In Twilio console (https://console.twilio.com), go to **Phone Numbers → Manage → Buy a number**
2. Buy a number with SMS capability (~$1.15/mo)
3. Click on the number → under **Messaging**, set:
   - "A message comes in" → Webhook → `https://aigovops-automation.fly.dev/webhook/twilio`
   - Method: POST
4. Add the phone number to Fly secrets:
   ```
   fly secrets set -a aigovops-automation TWILIO_PHONE_NUMBER="+1XXXXXXXXXX"
   ```

#### For Ken:

1. Bob gives you the Twilio phone number
2. Save it in your contacts as "AIGovOps Bot"
3. Text it any command: `status`, `costs`, `pending`

#### Using SMS:

- Text any command to the bot's number
- Keep messages short — SMS has a 1600 character limit for replies
- Best for quick checks: `status`, `pending`, `approve [id]`
- For longer outputs (research, drafts), use Telegram or Web instead

#### Tips:

- SMS costs ~$0.0079 per message (both directions)
- Great for quick approvals when you're away from your phone's apps

---

### 5. Email Commands

#### Setup:

Already working — no extra setup needed. The bot checks your Gmail every 5 minutes.

#### How to send a command via email:

1. Open your email (Outlook, Gmail, whatever you use)
2. Compose a new email
3. Send it **to yourself** (bobrapp@gmail.com) with a subject line starting with `cmd:`
4. Examples:
   - Subject: `cmd: status`
   - Subject: `cmd: draft about AI governance in healthcare`
   - Subject: `cmd: pending`
   - Subject: `cmd: approve a3f2b1c4`
5. The bot picks it up within 5 minutes
6. The result is sent to your Telegram

#### Alternative: use the body instead

- Subject: `cmd:`
- Body (first line): `research`

The bot reads the first line of the body if the subject is just `cmd:`.

#### Tips:

- Results come back via Telegram (not email reply) — this keeps things simple
- Good for when you're in Outlook and don't want to switch apps
- The 5-minute delay means this isn't great for urgent approvals — use Telegram or Web for those

---

## Feature Guide

---

### Email Triage (automatic)

**What it does:** Every 5 minutes, the bot checks your Gmail inbox for new unread emails. It classifies each one and only bothers you about the important ones.

**Categories:**
| Category | What happens |
|----------|-------------|
| 🔴 action-required | You get a Telegram notification with a draft reply |
| ℹ️ FYI-only | Silently archived — no notification |
| 📰 newsletter | Silently archived |
| 🗑️ spam | Silently archived |
| 🏛️ foundation-business | You get a Telegram notification |

**You don't need to do anything** — it runs automatically. You'll only hear from it when something needs your attention.

---

### Content Drafting

**What it does:** Writes LinkedIn posts in the AIGovOps Foundation voice.

**How to use:**
1. Send: `draft about [your topic]`
2. The bot writes a 100-150 word post
3. You get the draft with Approve/Reject options
4. Tap Approve → it's ready to post
5. Tap Reject → it's discarded

**Voice rules the bot follows:**
- Practitioner-first (not academic)
- No superlatives ("best ever", "amazing")
- No CTAs ("click here", "sign up")
- 100-150 words

**Example topics:**
- `draft about governance-as-code adoption`
- `draft about why AI audit trails matter`
- `draft about the gap between AI policy and practice`

---

### Research Scanning

**What it does:** Finds current AI governance news and scores it by relevance.

**How to use:**
1. Send: `research`
2. The bot returns 3 items with relevance scores (1-5)
3. Each item has a title and one-sentence summary

**When to use it:**
- Morning routine — check what's new in AI governance
- Before writing content — find fresh angles
- Weekly prep — stay current for meetings

---

### Cost Tracking

**What it does:** Tracks every LLM call by agent and model. Shows you exactly what you're spending.

**How to use:**
1. Send: `costs`
2. You get a 7-day breakdown: total spend, calls, cache savings, per-agent costs

**What it tracks:**
- Every draft, classification, research scan
- Token counts (input + output)
- Cost per agent
- Cache hit rate (cached calls are free)

**Expected costs:** ~$2-5/month total for normal usage.

---

### Approval Queue

**What it does:** Anything the bot creates (drafts, email replies) goes into a queue. Nothing gets sent or published without your approval.

**How to use:**
1. Send: `pending` — see what's waiting
2. Send: `approve [first 8 chars of ID]` — approve it
3. Send: `reject [first 8 chars of ID]` — reject it

**On Telegram:** You get inline buttons (✅ ❌) so you don't need to type the ID.

**On Web:** Approve/Reject buttons appear below each pending item.

---

### Audit Trail

**What it does:** Logs every action the bot takes — classifications, drafts, approvals, rejections, errors.

**How to use:**
1. Send: `audit`
2. You see the last 10 entries with timestamp, agent, action, and status

**Why it matters:**
- Full accountability — you can see exactly what happened and when
- Debugging — if something seems off, check the audit trail
- Compliance — every AI action is logged (the "GovOps" in AIGovOps)

---

## Daily Workflow (5 minutes)

Here's how Bob and Ken typically use the bot each day:

**Morning (1 minute):**
1. Check Telegram for any overnight notifications (action-required emails)
2. Approve or reject any pending items

**Midday (2 minutes):**
1. `research` — scan for news
2. `draft about [something from the research]` — create content
3. Approve the draft

**End of day (2 minutes):**
1. `pending` — clear the queue
2. `costs` — quick sanity check
3. Done

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Bot doesn't respond on Telegram | Check `/status` — if no response, the bot may be restarting. Wait 30 seconds. |
| "Access denied" on Telegram | Your chat ID isn't registered. Tell Bob. |
| Web UI shows "Error" | Try refreshing. If persistent, the bot may be restarting. |
| Email commands not working | They take up to 5 minutes. Check Telegram for the result. |
| WhatsApp not responding | Resend the sandbox join code — sessions expire after 72h. |
| Costs seem high | Send `costs` — if over $10/month, something unusual is happening. Normal is $2-5. |

---

## Security Notes

- Only Bob and Ken can use the Telegram bot (chat ID whitelist)
- The web UI is public but commands are harmless (no destructive actions)
- All secrets are in Fly.io (never in code or chat)
- The bot can classify and draft but **cannot send emails or post content** without your explicit approval
- The policy engine prevents agents from self-approving

---

## Quick Reference Card

```
COMMANDS:
  draft about [topic]     → AI writes content
  classify [email]        → Classify an email
  research                → AI governance news
  costs                   → 7-day spending
  status                  → Health check
  audit                   → Recent actions
  pending                 → Approval queue
  approve [id]            → Approve item
  reject [id]             → Reject item
  help                    → Show commands

CHANNELS:
  Telegram    → @aigovops_bot
  Web         → https://aigovops-automation.fly.dev/
  WhatsApp    → [Twilio sandbox number]
  SMS         → [Twilio phone number]
  Email       → Subject: cmd: [command]
```
