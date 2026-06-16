"""
Phase 2 — Tool implementations for Bright Smile Dental.

All implementations are MOCK/in-memory for learning. In Phase 3 these become
real integrations: a calendar API (NexHealth, Dentrix), a CRM for messages,
and a telephony transfer command to your Twilio/CCaaS layer.

Each tool follows the same pattern:
    async def handle_<name>(params: FunctionCallParams) -> None
        ... do the work ...
        await params.result_callback(result_string)

The result_callback injects the result back into the LLM context so the bot
can speak a natural response ("Great, I've booked you for Tuesday at 10am.")
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger
from pipecat.services.llm_service import FunctionCallParams
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema

# Use real Google Calendar when token.json exists, mock otherwise
_USE_GOOGLE = Path("token.json").exists()
if _USE_GOOGLE:
    from calendar_google import get_available_slots as _gcal_slots, book_appointment as _gcal_book
    logger.info("[calendar] Using real Google Calendar")
else:
    logger.info("[calendar] token.json not found — using mock calendar (run: uv run python calendar_google.py)")

_BOOKED_SLOTS: list[dict] = []


def _mock_available_slots() -> list[dict]:
    slots = []
    dt = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    while len(slots) < 5:
        if dt.weekday() < 5 and 8 <= dt.hour < 17:
            label = dt.strftime("%A %B %d at %I%p").replace(" 0", " ").replace("AM", "am").replace("PM", "pm")
            end = dt + timedelta(hours=1)
            slots.append({"label": label, "start": dt.isoformat(), "end": end.isoformat()})
        dt += timedelta(hours=1)
    return slots


def _get_slots(tenant: dict) -> list[dict]:
    if _USE_GOOGLE:
        cal_id = tenant.get("google_calendar_id", os.getenv("GOOGLE_CALENDAR_ID", "primary"))
        return _gcal_slots(cal_id, days_ahead=7, count=5)
    return _mock_available_slots()


# ---------------------------------------------------------------------------
# Tool: check_availability
# ---------------------------------------------------------------------------

async def handle_check_availability(params: FunctionCallParams) -> None:
    tenant = (params.app_resources or {}).get("tenant", {})
    slots = _get_slots(tenant)
    labels = [s["label"] for s in slots[:3]]
    result = "Available slots: " + ", ".join(labels) + "."
    logger.info(f"[tool] check_availability → {result}")
    # Cache slots so book_appointment can look up start/end times by label
    if params.app_resources is not None:
        params.app_resources["last_slots"] = {s["label"]: s for s in slots}
    await params.result_callback(result)


check_availability_schema = FunctionSchema(
    name="check_availability",
    description="Check the next available appointment slots at the dental practice.",
    properties={},
    required=[],
)


# ---------------------------------------------------------------------------
# Tool: book_appointment
# ---------------------------------------------------------------------------

async def handle_book_appointment(params: FunctionCallParams) -> None:
    args = params.arguments
    name = args.get("patient_name", "Unknown")
    slot_label = args.get("slot", "next available")
    service = args.get("service", "checkup")
    phone = args.get("phone", "")

    booking = {"name": name, "slot": slot_label, "service": service, "phone": phone}
    _BOOKED_SLOTS.append(booking)

    if _USE_GOOGLE:
        tenant = (params.app_resources or {}).get("tenant", {})
        cal_id = tenant.get("google_calendar_id", os.getenv("GOOGLE_CALENDAR_ID", "primary"))
        # Retrieve cached slot times from check_availability, fall back to mock
        slot_data = (params.app_resources or {}).get("last_slots", {}).get(slot_label)
        if slot_data:
            link = _gcal_book(cal_id, name, slot_data["start"], slot_data["end"], service, phone)
            logger.info(f"[tool] book_appointment (Google) → {link}")
        else:
            logger.warning("[tool] book_appointment: slot times not found, skipping Google Calendar write")
    else:
        logger.info(f"[tool] book_appointment (mock) → {booking}")

    if params.app_resources is not None:
        params.app_resources["outcome"] = "booked"
        params.app_resources["caller_name"] = name

    result = f"Appointment confirmed for {name} on {slot_label} for a {service}."
    if phone:
        result += f" Confirmation will be sent to {phone}."
    await params.result_callback(result)


book_appointment_schema = FunctionSchema(
    name="book_appointment",
    description=(
        "Book a dental appointment for a patient. Call this once you have collected "
        "the patient's name, preferred slot, and service type."
    ),
    properties={
        "patient_name": {"type": "string", "description": "Full name of the patient."},
        "slot": {"type": "string", "description": "The appointment slot, e.g. 'Monday June 10 at 9am'."},
        "service": {"type": "string", "description": "Type of dental service, e.g. 'cleaning', 'filling', 'emergency visit'."},
        "phone": {"type": "string", "description": "Patient's callback phone number (optional)."},
    },
    required=["patient_name", "slot", "service"],
)


# ---------------------------------------------------------------------------
# Tool: take_message
# ---------------------------------------------------------------------------

async def handle_take_message(params: FunctionCallParams) -> None:
    args = params.arguments
    caller_name = args.get("caller_name", "Unknown caller")
    message = args.get("message", "")
    callback_number = args.get("callback_number", "")

    record = {
        "caller": caller_name,
        "message": message,
        "callback": callback_number,
        "timestamp": datetime.now().isoformat(),
    }
    # In Phase 3: POST to CRM, send SMS/email to office
    logger.info(f"[tool] take_message → {json.dumps(record)}")

    if params.app_resources is not None:
        params.app_resources["outcome"] = "message"
        params.app_resources["caller_name"] = caller_name

    result = f"Message recorded for {caller_name}."
    if callback_number:
        result += f" The office will call back at {callback_number}."
    await params.result_callback(result)


take_message_schema = FunctionSchema(
    name="take_message",
    description=(
        "Record a message from the caller to be passed to the office. "
        "Use this when the caller wants a callback, has a question you cannot answer, "
        "or when the office is closed."
    ),
    properties={
        "caller_name": {"type": "string", "description": "Name of the caller."},
        "message": {"type": "string", "description": "The message content."},
        "callback_number": {"type": "string", "description": "Phone number for the office to call back."},
    },
    required=["caller_name", "message"],
)


# ---------------------------------------------------------------------------
# Tool: transfer_to_human
# ---------------------------------------------------------------------------

async def handle_transfer_to_human(params: FunctionCallParams) -> None:
    args = params.arguments
    reason = args.get("reason", "caller request")
    urgency = args.get("urgency", "normal")  # "emergency" | "normal"

    if params.app_resources is not None:
        params.app_resources["outcome"] = "transfer"

    if urgency == "emergency":
        result = "EMERGENCY_TRANSFER: connecting to on-call dentist now."
        logger.warning(f"[tool] EMERGENCY transfer — reason: {reason}")
    else:
        result = "TRANSFER: connecting to the front desk."
        logger.info(f"[tool] transfer_to_human — reason: {reason}")

    await params.result_callback(result)


transfer_to_human_schema = FunctionSchema(
    name="transfer_to_human",
    description=(
        "Transfer the caller to a human. Use urgency='emergency' for dental emergencies "
        "(knocked-out tooth, severe bleeding, facial trauma). Use urgency='normal' when "
        "the caller asks for a human or has a question you cannot handle."
    ),
    properties={
        "reason": {"type": "string", "description": "Brief reason for the transfer."},
        "urgency": {
            "type": "string",
            "enum": ["normal", "emergency"],
            "description": "'emergency' for dental emergencies, 'normal' otherwise.",
        },
    },
    required=["reason", "urgency"],
)


# ---------------------------------------------------------------------------
# Exported: tools schema + handler map
# ---------------------------------------------------------------------------

TOOLS_SCHEMA = ToolsSchema(standard_tools=[
    check_availability_schema,
    book_appointment_schema,
    take_message_schema,
    transfer_to_human_schema,
])

TOOL_HANDLERS = {
    "check_availability": handle_check_availability,
    "book_appointment": handle_book_appointment,
    "take_message": handle_take_message,
    "transfer_to_human": handle_transfer_to_human,
}
