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

import os
import re
import uuid
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
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
# Serve React build in production
# ---------------------------------------------------------------------------

frontend_dist = Path("frontend/dist")
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="static")
