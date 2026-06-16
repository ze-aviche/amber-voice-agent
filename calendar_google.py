"""
Google Calendar integration for Bright Smile Dental.

SETUP (one-time per practice):
  1. Go to console.cloud.google.com → New project → Enable "Google Calendar API"
  2. Create OAuth 2.0 credentials (Desktop app) → download as credentials.json
  3. Run:  uv run python calendar_google.py
     This opens a browser, you log in as the practice's Google account, and
     a token.json is saved. The bot uses that token.json from then on.

The token auto-refreshes — no re-auth needed unless revoked.

CALENDAR ID:
  - 'primary' = the main calendar of the logged-in Google account
  - For a shared practice calendar: paste the calendar ID from
    Google Calendar → Settings → that calendar → "Calendar ID"
  - Set it in .env as GOOGLE_CALENDAR_ID
"""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]

CREDENTIALS_FILE = Path("credentials.json")
TOKEN_FILE = Path("token.json")

# Appointment duration in minutes — make this per-service in Phase 3
SLOT_DURATION_MINUTES = 60

# Practice hours — make this per-tenant config in Phase 3
PRACTICE_OPEN_HOUR = 8
PRACTICE_CLOSE_HOUR = 17  # 5pm


def get_calendar_service():
    """Return an authenticated Google Calendar service object.

    Loads token.json if it exists (and refreshes if expired).
    Falls back to browser OAuth flow if no token yet.
    """
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    "credentials.json not found. Download it from Google Cloud Console "
                    "(APIs & Services → Credentials → OAuth 2.0 Client ID → Download)."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def get_available_slots(calendar_id: str, days_ahead: int = 7, count: int = 5) -> list[str]:
    """Return up to `count` open slots in the next `days_ahead` days.

    A slot is considered open if:
    - It falls within practice hours (Mon–Fri, 8am–5pm)
    - No existing event overlaps it (uses Google's freebusy API)

    Returns human-readable strings like "Monday June 9 at 10am".
    """
    service = get_calendar_service()
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days_ahead)

    # Ask Google which time ranges are already busy
    body = {
        "timeMin": now.isoformat(),
        "timeMax": end.isoformat(),
        "items": [{"id": calendar_id}],
    }
    freebusy = service.freebusy().query(body=body).execute()
    busy_periods = freebusy["calendars"].get(calendar_id, {}).get("busy", [])

    busy_ranges = [
        (
            datetime.fromisoformat(b["start"].replace("Z", "+00:00")),
            datetime.fromisoformat(b["end"].replace("Z", "+00:00")),
        )
        for b in busy_periods
    ]

    # Walk forward in 1-hour increments and find open slots
    slots = []
    cursor = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    while len(slots) < count and cursor < end:
        is_weekday = cursor.weekday() < 5
        is_practice_hours = PRACTICE_OPEN_HOUR <= cursor.hour < PRACTICE_CLOSE_HOUR
        slot_end = cursor + timedelta(minutes=SLOT_DURATION_MINUTES)

        if is_weekday and is_practice_hours:
            overlaps = any(
                not (slot_end <= b_start or cursor >= b_end)
                for b_start, b_end in busy_ranges
            )
            if not overlaps:
                local = cursor.astimezone()
                label = local.strftime("%A %B %d at %I%p").replace(" 0", " ").replace("AM", "am").replace("PM", "pm")
                slots.append({"label": label, "start": cursor.isoformat(), "end": slot_end.isoformat()})

        cursor += timedelta(hours=1)

    return slots


def book_appointment(
    calendar_id: str,
    patient_name: str,
    slot_start: str,
    slot_end: str,
    service: str,
    phone: str = "",
) -> str:
    """Create a Google Calendar event for the appointment.

    Returns the event HTML link so the practice can view it.
    """
    service_obj = get_calendar_service()

    description = f"Service: {service}"
    if phone:
        description += f"\nCallback: {phone}"

    event = {
        "summary": f"{patient_name} — {service}",
        "description": description,
        "start": {"dateTime": slot_start, "timeZone": "America/Chicago"},
        "end": {"dateTime": slot_end, "timeZone": "America/Chicago"},
    }

    created = service_obj.events().insert(calendarId=calendar_id, body=event).execute()
    return created.get("htmlLink", "confirmed")


# ---------------------------------------------------------------------------
# Run this file directly to do the one-time OAuth setup
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Opening browser for Google Calendar authorization...")
    svc = get_calendar_service()
    print("✓ Authorized. token.json saved.")
    cal_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    slots = get_available_slots(cal_id, days_ahead=3, count=3)
    print(f"\nNext available slots on calendar '{cal_id}':")
    for s in slots:
        print(f"  {s['label']}")
