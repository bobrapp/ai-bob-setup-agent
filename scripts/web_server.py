"""Web server — FastAPI app serving the web UI + Twilio webhooks.

Provides:
- GET  /           → Web UI (command input + approval queue)
- POST /api/cmd    → Execute a command (JSON: {"text": "..."})
- POST /api/approve/:id  → Approve an item
- POST /api/reject/:id   → Reject an item
- GET  /api/pending      → List pending approvals
- GET  /api/status       → System status
- POST /webhook/twilio   → Twilio SMS/WhatsApp incoming messages
- GET  /health           → Health check

Runs on port 8000 (shared with the health endpoint).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

log = logging.getLogger("web")

app = FastAPI(title="AIGovOps Bot", version="3.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# These get set by run_bot.py at startup
_router = None
_store = None

# Auth token for web/API access (simple bearer token)
WEB_TOKEN = os.getenv("WEB_API_TOKEN", "aigovops2026")

# Twilio auth
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")


def _check_auth(request: Request) -> bool:
    """Simple token auth for API calls."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:] == WEB_TOKEN
    # Also check query param for simple web form
    token = request.query_params.get("token", "")
    return token == WEB_TOKEN


# ─── API endpoints ────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    pending = len(_store.get_pending_approvals()) if _store else 0
    return {"status": "ok", "version": "3.0", "pending_approvals": pending}


@app.post("/api/cmd")
async def api_command(request: Request):
    """Execute a command via the router."""
    if not _check_auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    body = await request.json()
    text = body.get("text", "").strip()
    if not text:
        return JSONResponse({"error": "empty command"}, status_code=400)
    result = _router.route(text, username="bob")
    return {"text": result.text, "approval_id": result.approval_id}


@app.get("/api/pending")
async def api_pending(request: Request):
    if not _check_auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    pending = _store.get_pending_approvals()
    return {"items": pending, "count": len(pending)}


@app.post("/api/approve/{item_id}")
async def api_approve(item_id: str, request: Request):
    if not _check_auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    result = _router.route(f"approve {item_id}", username="bob")
    return {"text": result.text}


@app.post("/api/reject/{item_id}")
async def api_reject(item_id: str, request: Request):
    if not _check_auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    result = _router.route(f"reject {item_id}", username="bob")
    return {"text": result.text}


@app.get("/api/status")
async def api_status(request: Request):
    if not _check_auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    result = _router.route("status", username="bob")
    return {"text": result.text}


# ─── Twilio webhook (WhatsApp + SMS) ──────────────────────────────────────────

@app.post("/webhook/twilio")
async def twilio_webhook(
    Body: str = Form(""),
    From: str = Form(""),
    To: str = Form(""),
    MessageSid: str = Form(""),
):
    """Handle incoming Twilio SMS/WhatsApp messages.

    Twilio sends form-encoded POST with Body, From, To, etc.
    WhatsApp messages come from 'whatsapp:+1234567890'.
    """
    channel = "whatsapp" if "whatsapp:" in From else "sms"
    log.info("Twilio %s from %s: %s", channel, From, Body[:50])

    if not Body.strip():
        return _twilio_response("Send a command. Try: help")

    # Route the command
    result = _router.route(Body.strip(), username="bob")

    # Log it
    if _store:
        _store.log_audit(
            agent=f"system/{channel}", action="command",
            result_summary=f"{channel} from {From}: {Body[:50]}",
        )

    return _twilio_response(result.text)


def _twilio_response(text: str) -> PlainTextResponse:
    """Format a TwiML response for Twilio."""
    # TwiML XML response
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{_escape_xml(text[:1500])}</Message>
</Response>"""
    return PlainTextResponse(content=twiml, media_type="application/xml")


def _escape_xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ─── Web UI ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def web_ui(request: Request):
    """Serve the web command interface."""
    token = request.query_params.get("token", "")
    return HTMLResponse(content=_render_web_ui(token))


def _render_web_ui(token: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AIGovOps Bot — Web Interface</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#f8f9fa; color:#1a1a2e; min-height:100vh; }}
.container {{ max-width:700px; margin:0 auto; padding:1.5rem; }}
h1 {{ font-size:1.5rem; margin-bottom:0.5rem; }}
.subtitle {{ color:#666; font-size:0.9rem; margin-bottom:1.5rem; }}
.input-row {{ display:flex; gap:0.5rem; margin-bottom:1.5rem; }}
.input-row input {{ flex:1; padding:0.75rem 1rem; border:1px solid #ddd; border-radius:8px; font-size:1rem; }}
.input-row button {{ padding:0.75rem 1.5rem; background:#1a1a2e; color:white; border:none; border-radius:8px; font-size:1rem; cursor:pointer; }}
.input-row button:hover {{ background:#2d2d4e; }}
#output {{ background:white; border:1px solid #ddd; border-radius:8px; padding:1.25rem; min-height:200px; white-space:pre-wrap; font-family:'JetBrains Mono',monospace; font-size:0.85rem; line-height:1.6; }}
.pending {{ margin-top:1.5rem; }}
.pending h3 {{ font-size:1rem; margin-bottom:0.75rem; }}
.item {{ background:white; border:1px solid #ddd; border-radius:8px; padding:1rem; margin-bottom:0.75rem; }}
.item .desc {{ font-size:0.9rem; margin-bottom:0.5rem; }}
.item .actions {{ display:flex; gap:0.5rem; }}
.item .actions button {{ padding:0.4rem 0.8rem; border:none; border-radius:6px; font-size:0.8rem; cursor:pointer; font-weight:600; }}
.btn-approve {{ background:#d4edda; color:#155724; }}
.btn-reject {{ background:#f8d7da; color:#721c24; }}
.quick-btns {{ display:flex; flex-wrap:wrap; gap:0.4rem; margin-bottom:1rem; }}
.quick-btns button {{ padding:0.4rem 0.8rem; background:#e9ecef; border:1px solid #ddd; border-radius:6px; font-size:0.8rem; cursor:pointer; }}
.quick-btns button:hover {{ background:#dee2e6; }}
</style>
</head>
<body>
<div class="container">
  <h1>🤖 AIGovOps Bot</h1>
  <p class="subtitle">Web interface — same commands as Telegram, WhatsApp, SMS, and email.</p>

  <div class="quick-btns">
    <button onclick="send('status')">Status</button>
    <button onclick="send('costs')">Costs</button>
    <button onclick="send('audit')">Audit</button>
    <button onclick="send('pending')">Pending</button>
    <button onclick="send('research')">Research</button>
    <button onclick="send('help')">Help</button>
  </div>

  <div class="input-row">
    <input type="text" id="cmd" placeholder="Type a command... (e.g. draft about AI governance)" onkeydown="if(event.key==='Enter')send()">
    <button onclick="send()">Send</button>
  </div>

  <div id="output">Ready. Type a command or click a quick button above.</div>

  <div class="pending" id="pending-section"></div>
</div>

<script>
const TOKEN = '{token or WEB_TOKEN}';
const API = window.location.origin;

async function send(text) {{
  const input = document.getElementById('cmd');
  const cmd = text || input.value.trim();
  if (!cmd) return;
  input.value = '';

  const output = document.getElementById('output');
  output.textContent = '⏳ Processing...';

  try {{
    const resp = await fetch(API + '/api/cmd', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + TOKEN }},
      body: JSON.stringify({{ text: cmd }}),
    }});
    const data = await resp.json();
    output.textContent = data.text || data.error || 'No response';
    loadPending();
  }} catch (e) {{
    output.textContent = '❌ Error: ' + e.message;
  }}
}}

async function loadPending() {{
  try {{
    const resp = await fetch(API + '/api/pending?token=' + TOKEN);
    const data = await resp.json();
    const section = document.getElementById('pending-section');
    if (!data.items || data.items.length === 0) {{
      section.innerHTML = '';
      return;
    }}
    let html = '<h3>📋 Pending Approvals (' + data.items.length + ')</h3>';
    data.items.forEach(item => {{
      const shortId = item.id.substring(0, 8);
      html += '<div class="item">';
      html += '<div class="desc"><strong>' + item.action_type + '</strong>: ' + item.description.substring(0, 80) + '</div>';
      html += '<div class="actions">';
      html += '<button class="btn-approve" onclick="doAction(\\'approve\\',\\'' + shortId + '\\')">✅ Approve</button>';
      html += '<button class="btn-reject" onclick="doAction(\\'reject\\',\\'' + shortId + '\\')">❌ Reject</button>';
      html += '</div></div>';
    }});
    section.innerHTML = html;
  }} catch (e) {{ /* ignore */ }}
}}

async function doAction(action, id) {{
  await send(action + ' ' + id);
}}

// Load pending on page load
loadPending();
</script>
</body>
</html>"""
