"""API Gateway — FastAPI backend serving all interfaces.

Web, Mobile (PWA), Telegram, WhatsApp, Voice (Siri/Alexa), SMS — all hit this API.
WebSocket for real-time updates to web/mobile clients.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.personal_foundation.v2.state import StateStore

log = logging.getLogger(__name__)

JWT_SECRET = os.getenv("JWT_SECRET", "aigovops-dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
OPERATORS = {"bob": "Bob Rapp", "ken": "Ken Johnston"}

app = FastAPI(
    title="AIGovOps Foundation Automation API",
    version="2.0.0",
    description="Multi-interface API for the personal + foundation automation system.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # PWA served from any origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve PWA static files
WEB_DIR = Path(__file__).resolve().parent.parent.parent.parent / "web" / "public"
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

# Global state store (initialized on startup)
_store: StateStore | None = None
_ws_clients: list[WebSocket] = []


def get_store() -> StateStore:
    global _store
    if _store is None:
        _store = StateStore()
    return _store


# ------------------------------------------------------------------
# Auth
# ------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    token: str
    operator: str
    expires_at: str


def verify_token(authorization: str = Header(None)) -> dict:
    """Verify JWT token from Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")


@app.post("/api/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    """Login and get a JWT token. Bob and Ken only."""
    # Simple password check (in production, use proper auth)
    valid_passwords = {
        "bob": os.getenv("BOB_PASSWORD", "aigovops2026"),
        "ken": os.getenv("KEN_PASSWORD", "aigovops2026"),
    }
    if req.username not in valid_passwords or req.password != valid_passwords[req.username]:
        raise HTTPException(401, "Invalid credentials")

    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    token = jwt.encode(
        {"sub": req.username, "name": OPERATORS[req.username], "exp": expires},
        JWT_SECRET, algorithm=JWT_ALGORITHM,
    )
    return TokenResponse(token=token, operator=req.username, expires_at=expires.isoformat())


# ------------------------------------------------------------------
# Approval Queue
# ------------------------------------------------------------------

class ApprovalAction(BaseModel):
    action: str  # approve, reject, edit
    reason: str = ""
    new_content: str = ""


@app.get("/api/queue")
async def get_queue(user: dict = Depends(verify_token)):
    """Get all pending approval items."""
    store = get_store()
    return {"items": store.get_pending_approvals(), "count": len(store.get_pending_approvals())}


@app.post("/api/queue/{item_id}")
async def act_on_item(item_id: str, body: ApprovalAction, user: dict = Depends(verify_token)):
    """Approve, reject, or edit an approval queue item."""
    store = get_store()
    reviewer = user.get("sub", "unknown")

    if body.action == "approve":
        result = store.approve_item(item_id, reviewer)
        # Notify all WebSocket clients
        await broadcast({"type": "approval.approved", "item_id": item_id, "reviewer": reviewer})
    elif body.action == "reject":
        result = store.reject_item(item_id, reviewer, body.reason)
        await broadcast({"type": "approval.rejected", "item_id": item_id, "reviewer": reviewer})
    elif body.action == "edit":
        result = store.edit_item(item_id, body.new_content)
        await broadcast({"type": "approval.edited", "item_id": item_id})
    else:
        raise HTTPException(400, f"Invalid action: {body.action}")

    store.log_audit(
        agent="system/api", action=f"queue_{body.action}",
        operator=reviewer, result_summary=f"{body.action} item {item_id}",
    )
    return result


# ------------------------------------------------------------------
# Agents
# ------------------------------------------------------------------

class AgentAction(BaseModel):
    action: str  # suspend, resume
    reason: str = ""


@app.get("/api/agents")
async def list_agents(user: dict = Depends(verify_token)):
    """List all agents and their status."""
    store = get_store()
    # Get all known agents from agent_state table
    with store._conn() as conn:
        rows = conn.execute("SELECT * FROM agent_state ORDER BY agent").fetchall()
    return {"agents": [dict(r) for r in rows]}


@app.post("/api/agents/{agent_name}")
async def control_agent(agent_name: str, body: AgentAction, user: dict = Depends(verify_token)):
    """Suspend or resume an agent."""
    store = get_store()
    if body.action == "suspend":
        store.suspend_agent(agent_name, body.reason)
        store.log_audit(agent="system/api", action="suspend_agent",
                       operator=user["sub"], result_summary=f"Suspended {agent_name}: {body.reason}")
    elif body.action == "resume":
        store.resume_agent(agent_name)
        store.log_audit(agent="system/api", action="resume_agent",
                       operator=user["sub"], result_summary=f"Resumed {agent_name}")
    else:
        raise HTTPException(400, f"Invalid action: {body.action}")

    await broadcast({"type": f"agent.{body.action}", "agent": agent_name})
    return {"status": "ok", "agent": agent_name, "action": body.action}


# ------------------------------------------------------------------
# Audit Log
# ------------------------------------------------------------------

@app.get("/api/audit")
async def get_audit(
    limit: int = 100, agent: str = "", status: str = "", date: str = "",
    user: dict = Depends(verify_token),
):
    """Read audit log with optional filters."""
    store = get_store()
    entries = store.get_audit_log(limit=limit, agent=agent, status=status, date=date)
    return {"entries": entries, "count": len(entries)}


# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------

@app.get("/api/health")
async def health():
    """Public health endpoint (no auth required)."""
    store = get_store()
    pending = store.get_pending_approvals()
    return {
        "status": "ok",
        "pending_approvals": len(pending),
        "version": "2.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/costs")
async def get_costs(user: dict = Depends(verify_token)):
    """Get cost tracking data."""
    from src.personal_foundation.v2.cost_tracker import CostTracker
    store = get_store()
    tracker = CostTracker(store)
    return tracker.get_weekly_report()


@app.get("/api/cache/stats")
async def get_cache_stats(user: dict = Depends(verify_token)):
    """Get LLM cache statistics."""
    from src.personal_foundation.v2.cache import LLMCache
    store = get_store()
    cache = LLMCache(store)
    return cache.stats


@app.get("/api/feedback/stats")
async def get_feedback_stats(user: dict = Depends(verify_token)):
    """Get feedback loop statistics."""
    from src.personal_foundation.v2.feedback import FeedbackStore
    store = get_store()
    fb = FeedbackStore(store)
    return fb.get_stats()


@app.get("/api/research/stats")
async def get_research_stats(user: dict = Depends(verify_token)):
    """Get research RAG index statistics."""
    from src.personal_foundation.v2.rag import ResearchRAG
    store = get_store()
    rag = ResearchRAG(store)
    return rag.get_stats()


# ------------------------------------------------------------------
# Events (emit from external sources)
# ------------------------------------------------------------------

class EventPayload(BaseModel):
    event_type: str
    payload: dict = {}


@app.post("/api/events")
async def emit_event(body: EventPayload, user: dict = Depends(verify_token)):
    """Emit an event into the event bus (for external triggers)."""
    store = get_store()
    event_id = store.emit_event(body.event_type, body.payload)
    await broadcast({"type": "event.emitted", "event_type": body.event_type, "event_id": event_id})
    return {"event_id": event_id, "event_type": body.event_type}


# ------------------------------------------------------------------
# WebSocket (real-time updates for web/mobile)
# ------------------------------------------------------------------

@app.websocket("/ws/events")
async def websocket_events(ws: WebSocket):
    """WebSocket for real-time event streaming to web/mobile clients."""
    await ws.accept()
    _ws_clients.append(ws)
    log.info("WebSocket client connected (%d total)", len(_ws_clients))
    try:
        while True:
            # Keep connection alive; client can also send commands
            data = await ws.receive_text()
            # Handle client messages (e.g., approve from web UI)
            if data:
                import json
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "ping":
                        await ws.send_json({"type": "pong"})
                except Exception:
                    pass
    except WebSocketDisconnect:
        _ws_clients.remove(ws)
        log.info("WebSocket client disconnected (%d remaining)", len(_ws_clients))


async def broadcast(message: dict) -> None:
    """Broadcast a message to all connected WebSocket clients."""
    disconnected = []
    for ws in _ws_clients:
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        _ws_clients.remove(ws)


# ------------------------------------------------------------------
# Webhook receivers (for external services)
# ------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def serve_pwa():
    """Serve the PWA index.html."""
    from fastapi.responses import FileResponse
    index = WEB_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"message": "AIGovOps Automation API v2. Docs at /docs"}


@app.post("/webhooks/circle")
async def circle_webhook(payload: dict):
    """Receive Circle.so webhooks (member joined, post published, etc.)."""
    store = get_store()
    event_type = payload.get("event", "circle.unknown")
    # Map Circle events to our event types
    mapping = {
        "member_created": "member.joined",
        "post_created": "post.published",
        "comment_created": "post.published",
    }
    our_event = mapping.get(event_type, f"circle.{event_type}")
    store.emit_event(our_event, payload)
    return {"received": True, "mapped_to": our_event}


@app.post("/webhooks/make")
async def make_webhook(payload: dict):
    """Receive Make.com scenario completion webhooks."""
    store = get_store()
    store.log_audit(
        agent="foundation/make_shim", action="scenario_complete",
        result_summary=f"Make.com: {payload.get('scenario_name', 'unknown')} → {payload.get('status', 'unknown')}",
    )
    return {"received": True}


# ------------------------------------------------------------------
# Voice API (Siri Shortcuts / Alexa Skills)
# ------------------------------------------------------------------

class VoiceCommand(BaseModel):
    command: str  # "whats_pending", "approve_all_low_risk", "suspend", "daily_summary", "draft"
    params: dict = {}


@app.post("/api/voice")
async def voice_command(body: VoiceCommand, user: dict = Depends(verify_token)):
    """Handle voice commands from Siri Shortcuts or Alexa Skills.

    Supported commands:
    - whats_pending: Returns count and summary of pending items
    - approve_all_low_risk: Batch-approve items from low-risk agents
    - suspend: Suspend an agent (params: {agent: "name"})
    - daily_summary: What agents did today
    - draft: Trigger a content draft (params: {topic: "..."})
    """
    store = get_store()
    reviewer = user.get("sub", "unknown")

    if body.command == "whats_pending":
        items = store.get_pending_approvals()
        if not items:
            return {"speech": "No pending items. All clear.", "count": 0}
        summary = f"You have {len(items)} pending items. "
        agents = set(i["agent"] for i in items)
        summary += f"From: {', '.join(agents)}."
        return {"speech": summary, "count": len(items), "items": items[:5]}

    elif body.command == "approve_all_low_risk":
        # Low-risk = welcomer DMs, research digests, FYI archives
        low_risk_agents = ["foundation/welcomer", "personal/research_agent"]
        items = store.get_pending_approvals()
        approved = []
        for item in items:
            if item["agent"] in low_risk_agents:
                store.approve_item(item["id"], reviewer)
                approved.append(item["id"])
        return {"speech": f"Approved {len(approved)} low-risk items.", "approved": approved}

    elif body.command == "suspend":
        agent = body.params.get("agent", "")
        if not agent:
            return {"speech": "Which agent should I suspend?", "error": "missing_agent"}
        store.suspend_agent(agent, f"Voice command by {reviewer}")
        return {"speech": f"Suspended {agent}.", "agent": agent}

    elif body.command == "daily_summary":
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        entries = store.get_audit_log(limit=200, date=today)
        total = len(entries)
        successes = sum(1 for e in entries if e["status"] == "success")
        failures = sum(1 for e in entries if e["status"] == "failure")
        agents_active = len(set(e["agent"] for e in entries))
        speech = (
            f"Today your agents took {total} actions. "
            f"{successes} succeeded, {failures} failed. "
            f"{agents_active} agents were active."
        )
        return {"speech": speech, "total": total, "successes": successes, "failures": failures}

    elif body.command == "draft":
        topic = body.params.get("topic", "")
        if not topic:
            return {"speech": "What should I draft about?", "error": "missing_topic"}
        store.emit_event("draft.requested", {"topic": topic, "requester": reviewer})
        return {"speech": f"Draft requested about {topic}. I'll have it in your approval queue shortly."}

    else:
        return {"speech": f"I don't understand the command: {body.command}", "error": "unknown_command"}
