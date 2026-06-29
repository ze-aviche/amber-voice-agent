"""
FastAPI backend — serves the React frontend and exposes REST endpoints.

Endpoints:
  GET  /api/tenants                    — list all tenants
  GET  /api/tenants/{id}               — get one tenant
  POST /api/tenants                    — create tenant (onboarding wizard step 3)
  PUT  /api/tenants/{id}               — update tenant settings
  POST /api/tenants/scrape             — scrape a URL and return pre-filled config
  GET  /api/tenants/{id}/calls         — list calls for a tenant
  GET  /api/calls/{id}                 — get one call + transcript
  GET  /api/calls/{id}/recording       — stream the .wav recording

Run:
    uv run uvicorn api:app --reload --port 8000
"""

import asyncio
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from db import (
    init_db, get_tenant, list_tenants, upsert_tenant,
    get_call, list_calls,
)

app = FastAPI(title="Skove AI — Receptionist Platform")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

RECORDINGS_DIR = Path("recordings")
RECORDINGS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TenantCreate(BaseModel):
    id: str
    vertical: str
    name: str
    location: str | None = None
    hours: str | None = None
    phone: str | None = None
    services: list[str] = []
    google_calendar_id: str = "primary"
    emergency_triage: str | None = None
    human_handoff: str | None = None
    config: dict = {}


class TenantUpdate(BaseModel):
    name: str | None = None
    location: str | None = None
    hours: str | None = None
    phone: str | None = None
    services: list[str] | None = None
    google_calendar_id: str | None = None
    emergency_triage: str | None = None
    human_handoff: str | None = None
    config: dict | None = None


class ScrapeRequest(BaseModel):
    url: str
    vertical: str = "dental"


# ---------------------------------------------------------------------------
# Scraper — pulls basic business info from a URL
# ---------------------------------------------------------------------------

async def scrape_business(url: str, vertical: str) -> dict:
    """Fetch a business URL and extract basic info with simple heuristics.
    In production, replace with a proper LLM-based extraction."""
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            html = r.text
    except Exception:
        html = ""

    # Strip tags
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()[:3000]

    # Extract title
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE)
    name = title_match.group(1).strip() if title_match else url

    # Basic phone extraction
    phone_match = re.search(r"\(?\d{3}\)?[\s\-]\d{3}[\s\-]\d{4}", text)
    phone = phone_match.group(0) if phone_match else ""

    # Default services by vertical
    services = (
        ["cleanings and checkups", "fillings", "crowns", "teeth whitening", "emergency visits"]
        if vertical == "dental"
        else ["dine-in", "takeout", "curbside pickup"]
    )

    return {
        "name": name[:80],
        "location": "",
        "hours": "Monday to Friday, 9am to 5pm",
        "phone": phone,
        "services": services,
        "google_calendar_id": "primary",
        "emergency_triage": (
            "If the caller describes a knocked-out tooth, severe bleeding, or facial trauma, "
            "treat it as an EMERGENCY and call transfer_to_human with urgency=emergency."
        ) if vertical == "dental" else None,
        "human_handoff": "If the caller asks for a human or is upset, offer to take a message or transfer them.",
        "config": {},
        "_scraped_text": text[:500],
    }


# ---------------------------------------------------------------------------
# Tenant endpoints
# ---------------------------------------------------------------------------

@app.get("/api/tenants")
def api_list_tenants():
    return list_tenants()


@app.get("/api/tenants/{tenant_id}")
def api_get_tenant(tenant_id: str):
    t = get_tenant(tenant_id)
    if not t:
        raise HTTPException(404, f"Tenant '{tenant_id}' not found")
    return t


@app.post("/api/tenants", status_code=201)
def api_create_tenant(body: TenantCreate):
    existing = get_tenant(body.id)
    if existing:
        raise HTTPException(409, f"Tenant '{body.id}' already exists")
    upsert_tenant(body.model_dump())
    return get_tenant(body.id)


@app.put("/api/tenants/{tenant_id}")
def api_update_tenant(tenant_id: str, body: TenantUpdate):
    existing = get_tenant(tenant_id)
    if not existing:
        raise HTTPException(404, f"Tenant '{tenant_id}' not found")
    updated = {**existing, **{k: v for k, v in body.model_dump().items() if v is not None}}
    upsert_tenant(updated)
    return get_tenant(tenant_id)


@app.post("/api/tenants/scrape")
async def api_scrape(body: ScrapeRequest):
    data = await scrape_business(body.url, body.vertical)
    # Suggest an ID from the name
    raw = data["name"].lower()
    suggested_id = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:40]
    data["id"] = suggested_id
    data["vertical"] = body.vertical
    return data


# ---------------------------------------------------------------------------
# Call endpoints
# ---------------------------------------------------------------------------

@app.get("/api/tenants/{tenant_id}/calls")
def api_list_calls(tenant_id: str, limit: int = 50):
    t = get_tenant(tenant_id)
    if not t:
        raise HTTPException(404, f"Tenant '{tenant_id}' not found")
    return list_calls(tenant_id, limit=limit)


@app.get("/api/calls/{call_id}")
def api_get_call(call_id: str):
    c = get_call(call_id)
    if not c:
        raise HTTPException(404, f"Call '{call_id}' not found")
    return c


@app.get("/api/calls/{call_id}/recording")
def api_get_recording(call_id: str):
    c = get_call(call_id)
    if not c:
        raise HTTPException(404, "Call not found")
    if not c.get("recording_path"):
        raise HTTPException(404, "No recording for this call")
    path = RECORDINGS_DIR / c["recording_path"]
    if not path.exists():
        raise HTTPException(404, "Recording file not found")
    return FileResponse(str(path), media_type="audio/wav")


# ---------------------------------------------------------------------------
# Live call state — shared between bot.py (writer) and WebSocket (reader)
# ---------------------------------------------------------------------------
# call_id → {"transcript": [...], "sentiment": {...}, "outcome": str, "tenant_id": str}
_live_calls: dict[str, dict[str, Any]] = {}

# WebSocket connections subscribed to a call_id
_ws_subscribers: dict[str, list[WebSocket]] = {}


def publish_call_update(call_id: str, update: dict) -> None:
    """
    Called by bot.py (or tools) to push a transcript turn + sentiment reading.
    Stores the update in _live_calls and queues it for WebSocket broadcast.
    """
    if call_id not in _live_calls:
        _live_calls[call_id] = {"transcript": [], "sentiment": None, "outcome": "active"}
    state = _live_calls[call_id]
    if "turn" in update:
        state["transcript"].append(update["turn"])
    if "sentiment" in update:
        state["sentiment"] = update["sentiment"]
    if "outcome" in update:
        state["outcome"] = update["outcome"]

    # Fire-and-forget broadcast to connected supervisors
    subs = _ws_subscribers.get(call_id, [])
    if subs:
        payload = json.dumps({**state, "call_id": call_id})
        asyncio.create_task(_broadcast(call_id, payload))


async def _broadcast(call_id: str, payload: str) -> None:
    dead: list[WebSocket] = []
    for ws in list(_ws_subscribers.get(call_id, [])):
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_subscribers.get(call_id, []).remove(ws)


@app.websocket("/ws/calls/{call_id}")
async def ws_call_feed(websocket: WebSocket, call_id: str):
    """
    Supervisor dashboard connects here to receive live transcript + sentiment.
    Messages are JSON: {call_id, transcript, sentiment, outcome}

    Also accepts text messages from the client:
      {"action": "subscribe"}  — start streaming (sent automatically on connect)
    """
    await websocket.accept()
    _ws_subscribers.setdefault(call_id, []).append(websocket)

    # Send current state immediately on connect
    if call_id in _live_calls:
        await websocket.send_text(
            json.dumps({**_live_calls[call_id], "call_id": call_id})
        )

    try:
        while True:
            # Keep connection alive; data is pushed via publish_call_update
            await asyncio.sleep(30)
            await websocket.send_text(json.dumps({"ping": True, "call_id": call_id}))
    except (WebSocketDisconnect, Exception):
        subs = _ws_subscribers.get(call_id, [])
        if websocket in subs:
            subs.remove(websocket)


@app.get("/api/live-calls")
def api_live_calls():
    """List all calls currently tracked as active (useful for supervisor overview)."""
    return [
        {"call_id": cid, **state}
        for cid, state in _live_calls.items()
        if state.get("outcome") == "active"
    ]


@app.get("/api/live-calls/{call_id}")
def api_live_call(call_id: str):
    """Snapshot of current live call state (polling fallback for non-WS clients)."""
    state = _live_calls.get(call_id)
    if not state:
        raise HTTPException(404, f"No live call '{call_id}'")
    return {"call_id": call_id, **state}


# ---------------------------------------------------------------------------
# Loan Processing — LangGraph endpoints
# ---------------------------------------------------------------------------

class LoanApplicationRequest(BaseModel):
    customer_id: str
    customer_name: str
    business_name: str
    business_ein: str
    requested_amount: float
    loan_purpose: str


class UnderwriterDecision(BaseModel):
    decision: str          # "approved" | "declined"
    underwriter_id: str
    notes: str = ""


@app.post("/api/loans", status_code=202)
async def api_start_loan(body: LoanApplicationRequest):
    """
    Start a new loan application. Kicks off the LangGraph workflow async.
    Returns immediately with the application_id — graph runs in background.

    Demo flow:
      POST /api/loans          → application_id returned
      GET  /api/loans/{id}     → poll status (parallel checks running...)
      GET  /api/loans/{id}     → status = "manual_review", is_interrupted = true
      POST /api/loans/{id}/decision → underwriter approves/declines
      GET  /api/loans/{id}     → status = "offer_generation", offer terms visible
    """
    from loan.graph import get_loan_graph
    from datetime import datetime, timezone

    app_id = f"LOAN-{uuid.uuid4().hex[:8].upper()}"
    config = {"configurable": {"thread_id": app_id}}
    loan_graph = await get_loan_graph()

    initial_state = {
        "application_id": app_id,
        "customer_id": body.customer_id,
        "customer_name": body.customer_name,
        "business_name": body.business_name,
        "business_ein": body.business_ein,
        "requested_amount": body.requested_amount,
        "loan_purpose": body.loan_purpose,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "kyc_status": "pending",
        "adverse_action_sent": False,
        "current_node": "start",
        "session_count": 1,
        # Optional fields — all None initially
        "kyc_failure_reason": None,
        "credit_score": None,
        "credit_report_summary": None,
        "fraud_score": None,
        "fraud_flags": None,
        "business_verified": None,
        "business_state": None,
        "business_incorporation_date": None,
        "tax_transcripts_received": None,
        "annual_revenue": None,
        "underwriting_decision": None,
        "decline_reasons": None,
        "auto_decision_rationale": None,
        "underwriter_id": None,
        "underwriter_notes": None,
        "underwriter_decision": None,
        "underwriter_decided_at": None,
        "approved_amount": None,
        "interest_rate": None,
        "term_months": None,
        "monthly_payment": None,
        "offer_generated_at": None,
        "ecoa_disclosed_at": None,
        "error_message": None,
    }

    # Run graph in background — it will checkpoint at each node then pause at interrupt
    async def _run():
        try:
            g = await get_loan_graph()
            async for _ in g.astream(initial_state, config):
                pass
        except Exception as exc:
            from loguru import logger
            logger.error(f"[loan:{app_id}] graph error: {exc}")

    asyncio.create_task(_run())
    return {"application_id": app_id, "status": "processing"}


@app.get("/api/loans")
async def api_list_loans():
    """List all loan applications with their current status."""
    from loan.graph import list_applications
    return await list_applications()


@app.get("/api/loans/{application_id}")
async def api_get_loan(application_id: str):
    """Get full state of a single loan application."""
    from loan.graph import get_application_state
    state = await get_application_state(application_id)
    if not state:
        raise HTTPException(404, f"Application '{application_id}' not found")
    return state


@app.post("/api/loans/{application_id}/decision")
async def api_underwriter_decision(application_id: str, body: UnderwriterDecision):
    """
    Underwriter approves or declines a loan that is waiting at the human gate.
    This resumes the LangGraph from the interrupt point.

    Behind the scenes:
      loan_graph.update_state() injects the decision into checkpointed state
      loan_graph.astream() resumes from underwriter_review → next node
    """
    from loan.graph import get_loan_graph, get_application_state

    state = await get_application_state(application_id)
    if not state:
        raise HTTPException(404, f"Application '{application_id}' not found")
    if not state.get("_is_interrupted"):
        raise HTTPException(400, "Application is not currently awaiting underwriter review")

    if body.decision not in ("approved", "declined"):
        raise HTTPException(422, "decision must be 'approved' or 'declined'")

    loan_graph = await get_loan_graph()
    config = {"configurable": {"thread_id": application_id}}

    # Inject underwriter's decision into the checkpointed state
    await loan_graph.aupdate_state(config, {
        "underwriter_decision": body.decision,
        "underwriter_id": body.underwriter_id,
        "underwriter_notes": body.notes,
    }, as_node="underwriter_review")

    # Resume the graph from the interrupt point
    async def _resume():
        try:
            g = await get_loan_graph()
            async for _ in g.astream(None, config):
                pass
        except Exception as exc:
            from loguru import logger
            logger.error(f"[loan:{application_id}] resume error: {exc}")

    asyncio.create_task(_resume())
    return {"application_id": application_id, "decision": body.decision, "status": "resuming"}


# ---------------------------------------------------------------------------
# Serve React build in production
# ---------------------------------------------------------------------------

frontend_dist = Path("frontend/dist")
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="static")
