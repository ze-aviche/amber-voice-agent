"""
SQLite database — tenant config store.

Schema: one row per business (tenant). The voice engine loads this row at
call-start and generates the system prompt + tool config from it.
Adding a new client = inserting a row. No code change required.

In production (Phase 4+) swap the DB_PATH env var to a Postgres URL and
replace sqlite3 with asyncpg — the rest of the codebase stays the same.
"""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path("tenants.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create all tables if they don't exist."""
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tenants (
                id                  TEXT PRIMARY KEY,
                vertical            TEXT NOT NULL,
                name                TEXT NOT NULL,
                location            TEXT,
                hours               TEXT,
                phone               TEXT,
                services            TEXT,
                google_calendar_id  TEXT DEFAULT 'primary',
                emergency_triage    TEXT,
                human_handoff       TEXT,
                config              TEXT DEFAULT '{}'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS calls (
                id              TEXT PRIMARY KEY,
                tenant_id       TEXT NOT NULL REFERENCES tenants(id),
                started_at      TEXT NOT NULL,
                ended_at        TEXT,
                duration_secs   INTEGER,
                outcome         TEXT,   -- 'active' | 'booked' | 'message' | 'transfer' | 'info' | 'abandoned'
                caller_number   TEXT,
                transcript      TEXT,   -- JSON array of {role, text} turns
                recording_path  TEXT,   -- relative path to .wav file
                summary         TEXT    -- one-line LLM summary of the call
            )
        """)
        conn.commit()


def get_tenant(tenant_id: str) -> dict | None:
    """Load a tenant by ID. Returns a plain dict or None if not found."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM tenants WHERE id = ?", (tenant_id,)
        ).fetchone()
    if not row:
        return None
    t = dict(row)
    t["services"] = json.loads(t["services"] or "[]")
    t["config"] = json.loads(t["config"] or "{}")
    return t


def list_tenants() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM tenants ORDER BY name").fetchall()
    result = []
    for row in rows:
        t = dict(row)
        t["services"] = json.loads(t["services"] or "[]")
        t["config"] = json.loads(t["config"] or "{}")
        result.append(t)
    return result


def upsert_tenant(tenant: dict) -> None:
    """Insert or replace a tenant record."""
    t = tenant.copy()
    t["services"] = json.dumps(t.get("services", []))
    t["config"] = json.dumps(t.get("config", {}))
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO tenants
                (id, vertical, name, location, hours, phone, services,
                 google_calendar_id, emergency_triage, human_handoff, config)
            VALUES
                (:id, :vertical, :name, :location, :hours, :phone, :services,
                 :google_calendar_id, :emergency_triage, :human_handoff, :config)
            ON CONFLICT(id) DO UPDATE SET
                vertical           = excluded.vertical,
                name               = excluded.name,
                location           = excluded.location,
                hours              = excluded.hours,
                phone              = excluded.phone,
                services           = excluded.services,
                google_calendar_id = excluded.google_calendar_id,
                emergency_triage   = excluded.emergency_triage,
                human_handoff      = excluded.human_handoff,
                config             = excluded.config
        """, t)
        conn.commit()


# ---------------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------------

def insert_call(call: dict) -> None:
    c = call.copy()
    c["transcript"] = json.dumps(c.get("transcript", []))
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO calls
                (id, tenant_id, started_at, ended_at, duration_secs,
                 outcome, caller_number, transcript, recording_path, summary)
            VALUES
                (:id, :tenant_id, :started_at, :ended_at, :duration_secs,
                 :outcome, :caller_number, :transcript, :recording_path, :summary)
        """, c)
        conn.commit()


def update_call(call_id: str, **fields) -> None:
    if "transcript" in fields:
        fields["transcript"] = json.dumps(fields["transcript"])
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["call_id"] = call_id
    with get_conn() as conn:
        conn.execute(f"UPDATE calls SET {set_clause} WHERE id = :call_id", fields)
        conn.commit()


def list_calls(tenant_id: str, limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM calls WHERE tenant_id = ? ORDER BY started_at DESC LIMIT ?",
            (tenant_id, limit),
        ).fetchall()
    result = []
    for row in rows:
        c = dict(row)
        c["transcript"] = json.loads(c["transcript"] or "[]")
        result.append(c)
    return result


def get_call(call_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
    if not row:
        return None
    c = dict(row)
    c["transcript"] = json.loads(c["transcript"] or "[]")
    return c
