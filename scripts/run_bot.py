#!/usr/bin/env python3
"""AIGovOps Bot — Multi-channel AI operations bot.

Channels:
- Telegram (polling)
- Web UI (FastAPI on :8000)
- WhatsApp (Twilio webhook on /webhook/twilio)
- SMS (Twilio webhook on /webhook/twilio)
- Email commands (parsed from incoming emails)

All channels share one CommandRouter. One process. One deploy.

Run: python3 scripts/run_bot.py
"""

import asyncio
import json
import logging
import os
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler,
    MessageHandler, ContextTypes, filters,
)

from src.personal_foundation.v2.state import StateStore
from src.personal_foundation.v2.cost_tracker import CostTracker
from src.personal_foundation.v2.policy import PolicyEngine, PolicyContext
from scripts.command_router import CommandRouter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("bot")

# ─── Config ────────────────────────────────────────────────────────────────────

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
BOB_CHAT_ID = os.getenv("TELEGRAM_BOB_CHAT_ID", "")
KEN_CHAT_ID = os.getenv("TELEGRAM_KEN_CHAT_ID", "")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
EMAIL_POLLING_ENABLED = os.getenv("EMAIL_POLLING_ENABLED", "true").lower() == "true"

ALLOWED_CHAT_IDS = set()
if BOB_CHAT_ID:
    ALLOWED_CHAT_IDS.add(int(BOB_CHAT_ID))
if KEN_CHAT_ID:
    ALLOWED_CHAT_IDS.add(int(KEN_CHAT_ID))

# ─── Core services ────────────────────────────────────────────────────────────

store = StateStore()
cost_tracker = CostTracker(store)
policy_engine = PolicyEngine()


def call_llm(agent_name: str, system: str, user: str, json_mode: bool = False) -> str:
    """Call OpenAI and track cost."""
    import urllib.request
    if not OPENAI_KEY:
        return '{"error": "OPENAI_API_KEY not set"}'
    body = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": 500, "temperature": 0.3,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions", data=data,
        headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=30)
    result = json.loads(resp.read())
    usage = result.get("usage", {})
    cost_tracker.record(agent_name, "gpt-4o-mini",
                       usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
    return result["choices"][0]["message"]["content"]


# The shared router
router = CommandRouter(store, cost_tracker, policy_engine, call_llm)


# ─── Telegram handlers ────────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle approve/reject/edit button taps."""
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    parts = data.split(":", 1)
    if len(parts) != 2:
        return
    action, item_id = parts
    user = query.from_user.first_name or "Unknown"
    username = "bob" if str(query.from_user.id) == BOB_CHAT_ID else "ken"

    result = router.route(f"{action} {item_id}", username=username)
    await query.edit_message_text(result.text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Telegram text messages via the router."""
    if not update.message or not update.message.text:
        return
    chat_id = update.message.chat_id
    if ALLOWED_CHAT_IDS and chat_id not in ALLOWED_CHAT_IDS:
        await update.message.reply_text("⛔ Access denied.")
        return

    text = update.message.text.strip()
    username = "bob" if str(chat_id) == BOB_CHAT_ID else "ken"
    result = router.route(text, username=username)

    # If there's an approval item, add buttons
    if result.approval_id:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"approve:{result.approval_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject:{result.approval_id}"),
        ]])
        await update.message.reply_text(result.text, reply_markup=keyboard)
    else:
        await update.message.reply_text(result.text)


async def cmd_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /commands by routing them."""
    if not update.message:
        return
    chat_id = update.message.chat_id
    if ALLOWED_CHAT_IDS and chat_id not in ALLOWED_CHAT_IDS:
        await update.message.reply_text("⛔ Access denied.")
        return
    text = update.message.text.strip()
    username = "bob" if str(chat_id) == BOB_CHAT_ID else "ken"
    result = router.route(text, username=username)
    await update.message.reply_text(result.text)


# ─── Web UI HTML ───────────────────────────────────────────────────────────────

WEB_TOKEN = os.getenv("WEB_API_TOKEN", "aigovops2026")


def _get_web_ui_html() -> str:
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AIGovOps Bot</title><style>
*{margin:0;padding:0;box-sizing:border-box}body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f8f9fa;color:#1a1a2e;min-height:100vh}
.c{max-width:700px;margin:0 auto;padding:1.5rem}h1{font-size:1.5rem;margin-bottom:.5rem}.sub{color:#666;font-size:.9rem;margin-bottom:1.5rem}
.row{display:flex;gap:.5rem;margin-bottom:1.5rem}.row input{flex:1;padding:.75rem 1rem;border:1px solid #ddd;border-radius:8px;font-size:1rem}
.row button{padding:.75rem 1.5rem;background:#1a1a2e;color:#fff;border:none;border-radius:8px;font-size:1rem;cursor:pointer}
#out{background:#fff;border:1px solid #ddd;border-radius:8px;padding:1.25rem;min-height:200px;white-space:pre-wrap;font-family:monospace;font-size:.85rem;line-height:1.6}
.qb{display:flex;flex-wrap:wrap;gap:.4rem;margin-bottom:1rem}.qb button{padding:.4rem .8rem;background:#e9ecef;border:1px solid #ddd;border-radius:6px;font-size:.8rem;cursor:pointer}
.pend{margin-top:1.5rem}.item{background:#fff;border:1px solid #ddd;border-radius:8px;padding:1rem;margin-bottom:.75rem}
.item .acts{display:flex;gap:.5rem;margin-top:.5rem}.item .acts button{padding:.4rem .8rem;border:none;border-radius:6px;font-size:.8rem;cursor:pointer;font-weight:600}
.ba{background:#d4edda;color:#155724}.br{background:#f8d7da;color:#721c24}
</style></head><body><div class="c">
<h1>&#x1F916; AIGovOps Bot</h1><p class="sub">Web interface — same commands as Telegram, WhatsApp, SMS, and email.</p>
<div class="qb"><button onclick="s('status')">Status</button><button onclick="s('costs')">Costs</button><button onclick="s('audit')">Audit</button><button onclick="s('pending')">Pending</button><button onclick="s('research')">Research</button><button onclick="s('help')">Help</button></div>
<div class="row"><input id="cmd" placeholder="Type a command..." onkeydown="if(event.key==='Enter')s()"><button onclick="s()">Send</button></div>
<div id="out">Ready. Type a command or click a button above.</div><div class="pend" id="ps"></div>
</div><script>
const A=window.location.origin;
async function s(t){const i=document.getElementById('cmd');const c=t||i.value.trim();if(!c)return;i.value='';
const o=document.getElementById('out');o.textContent='Processing...';
try{const r=await fetch(A+'/api/cmd',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:c})});
const d=await r.json();o.textContent=d.text||d.error||'No response';lp();}catch(e){o.textContent='Error: '+e.message;}}
async function lp(){try{const r=await fetch(A+'/api/pending');const d=await r.json();const ps=document.getElementById('ps');
if(!d.items||!d.items.length){ps.innerHTML='';return;}
let h='<h3>Pending ('+d.items.length+')</h3>';
d.items.forEach(i=>{const id=i.id.substring(0,8);h+='<div class="item"><div>'+i.action_type+': '+i.description.substring(0,80)+'</div><div class="acts"><button class="ba" onclick="s(\\'approve '+id+'\\')">Approve</button><button class="br" onclick="s(\\'reject '+id+'\\')">Reject</button></div></div>';});
ps.innerHTML=h;}catch(e){}}lp();
</script></body></html>"""


# ─── Web server (simple HTTP) ──────────────────────────────────────────────────

def start_web_server():
    """Start a simple HTTP server for health + web UI + webhooks."""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import urllib.parse

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health" or self.path == "/":
                if self.path == "/health":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    pending = len(store.get_pending_approvals())
                    self.wfile.write(json.dumps({
                        "status": "ok", "version": "3.1",
                        "email_polling": EMAIL_POLLING_ENABLED,
                        "pending_approvals": pending,
                    }).encode())
                else:
                    # Serve web UI
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(_get_web_ui_html().encode())
            elif self.path.startswith("/api/pending"):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                pending = store.get_pending_approvals()
                self.wfile.write(json.dumps({"items": pending, "count": len(pending)}).encode())
            elif self.path.startswith("/api/status"):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                result = router.route("status")
                self.wfile.write(json.dumps({"text": result.text}).encode())
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length else b""

            if self.path == "/api/cmd":
                try:
                    data = json.loads(body)
                    text = data.get("text", "").strip()
                    result = router.route(text, username="bob")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"text": result.text, "approval_id": result.approval_id}).encode())
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode())

            elif self.path == "/webhook/twilio":
                # Parse form-encoded Twilio webhook
                form_data = urllib.parse.parse_qs(body.decode())
                msg_body = form_data.get("Body", [""])[0]
                from_num = form_data.get("From", [""])[0]
                channel = "whatsapp" if "whatsapp:" in from_num else "sms"

                log.info("Twilio %s from %s: %s", channel, from_num, msg_body[:50])

                if msg_body.strip():
                    result = router.route(msg_body.strip(), username="bob")
                    reply = result.text[:1500]
                else:
                    reply = "Send a command. Try: help"

                store.log_audit(agent=f"system/{channel}", action="command",
                              result_summary=f"{channel}: {msg_body[:50]}")

                # TwiML response
                twiml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{reply}</Message></Response>'
                self.send_response(200)
                self.send_header("Content-Type", "application/xml")
                self.end_headers()
                self.wfile.write(twiml.encode())

            elif self.path.startswith("/api/approve/"):
                item_id = self.path.split("/")[-1]
                result = router.route(f"approve {item_id}", username="bob")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"text": result.text}).encode())

            elif self.path.startswith("/api/reject/"):
                item_id = self.path.split("/")[-1]
                result = router.route(f"reject {item_id}", username="bob")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"text": result.text}).encode())

            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            pass  # Suppress access logs

    server = HTTPServer(("0.0.0.0", 8000), Handler)
    server.serve_forever()


# ─── Email polling ─────────────────────────────────────────────────────────────

async def start_email_polling(app: Application) -> None:
    """Start email polling as a background task."""
    if not EMAIL_POLLING_ENABLED:
        log.info("Email polling disabled")
        return
    from scripts.email_poller import poll_loop
    log.info("Starting email polling (5 min interval)...")
    asyncio.create_task(poll_loop())


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    # Start web server (FastAPI) in background thread
    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()
    log.info("Web server on :8000 (UI + WhatsApp/SMS webhooks)")

    # Start Telegram bot
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(CommandHandler("status", cmd_handler))
    app.add_handler(CommandHandler("costs", cmd_handler))
    app.add_handler(CommandHandler("audit", cmd_handler))
    app.add_handler(CommandHandler("help", cmd_handler))
    app.add_handler(CommandHandler("research", cmd_handler))
    app.add_handler(CommandHandler("pending", cmd_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.post_init = start_email_polling

    store.log_audit(agent="system/bot", action="startup",
                   result_summary="Bot v3.1 started. Channels: Telegram, Web, WhatsApp, SMS, Email")

    log.info("Bot v3.1 started. Channels: Telegram + Web + WhatsApp/SMS + Email polling")
    app.run_polling()


if __name__ == "__main__":
    main()
