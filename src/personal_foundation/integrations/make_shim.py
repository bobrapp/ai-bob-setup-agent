"""Make.com scenario completion webhook shim.

INTERNAL USE ONLY — not part of the ai-bob-setup-agent customer product.

Lightweight FastAPI app that Make.com calls at scenario completion.
Validates the payload and writes an audit log entry via audit_shim.

Run with:
    uvicorn src.personal_foundation.integrations.make_shim:app
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from src.personal_foundation import audit_shim

log = logging.getLogger(__name__)

app = FastAPI(title="Make.com Shim", docs_url=None, redoc_url=None)


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class MakeCompletionPayload(BaseModel):
    """Payload sent by Make.com at scenario completion."""

    scenario_name: str
    status: Literal["success", "failure"]
    timestamp: str  # ISO 8601
    details: dict = {}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/make-shim/scenario-complete")
def scenario_complete(payload: MakeCompletionPayload) -> dict:
    """Receive a Make.com scenario completion event and write an audit log entry."""
    audit_shim.log_action(
        action="foundation/make_shim:scenario_complete",
        command=f"make.com:{payload.scenario_name}",
        status=payload.status,
        result_summary=(
            f"Make.com scenario '{payload.scenario_name}' completed: {payload.status}"
        ),
        details=payload.details,
    )
    log.info(
        "make_shim.scenario_complete scenario=%r status=%s",
        payload.scenario_name,
        payload.status,
    )
    return {"ok": True, "logged": True}


@app.get("/health")
def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}
