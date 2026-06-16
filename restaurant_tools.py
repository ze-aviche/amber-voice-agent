"""
Restaurant vertical — tool implementations.

Same tool names and schema as dental tools so the pipeline wiring in bot.py
doesn't change. Only the handler logic differs.

check_availability → open reservation slots (reuses Google Calendar)
book_appointment   → reserve a table (creates Calendar event)
take_message       → record takeout order or callback request
transfer_to_human  → connect to manager
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger
from pipecat.services.llm_service import FunctionCallParams
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema

_USE_GOOGLE = Path("token.json").exists()
if _USE_GOOGLE:
    from calendar_google import get_available_slots as _gcal_slots, book_appointment as _gcal_book

_ORDERS: list[dict] = []


def _mock_slots() -> list[dict]:
    slots = []
    dt = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    while len(slots) < 5:
        if 11 <= dt.hour < 22:
            label = dt.strftime("%A %B %d at %I%p").replace(" 0", " ").replace("AM", "am").replace("PM", "pm")
            slots.append({"label": label, "start": dt.isoformat(), "end": (dt + timedelta(hours=2)).isoformat()})
        dt += timedelta(hours=1)
    return slots


def _get_slots(tenant: dict) -> list[dict]:
    if _USE_GOOGLE:
        cal_id = tenant.get("google_calendar_id", os.getenv("GOOGLE_CALENDAR_ID", "primary"))
        return _gcal_slots(cal_id, days_ahead=7, count=5)
    return _mock_slots()


async def handle_check_availability(params: FunctionCallParams) -> None:
    tenant = (params.app_resources or {}).get("tenant", {})
    slots = _get_slots(tenant)
    labels = [s["label"] for s in slots[:3]]
    result = "Available times: " + ", ".join(labels) + "."
    if params.app_resources is not None:
        params.app_resources["last_slots"] = {s["label"]: s for s in slots}
    logger.info(f"[restaurant tool] check_availability → {result}")
    await params.result_callback(result)


async def handle_book_appointment(params: FunctionCallParams) -> None:
    args = params.arguments
    name = args.get("patient_name", "Guest")
    slot_label = args.get("slot", "next available")
    party_size = args.get("service", "2")  # reuses "service" field for party size

    if _USE_GOOGLE:
        tenant = (params.app_resources or {}).get("tenant", {})
        cal_id = tenant.get("google_calendar_id", os.getenv("GOOGLE_CALENDAR_ID", "primary"))
        slot_data = (params.app_resources or {}).get("last_slots", {}).get(slot_label)
        if slot_data:
            _gcal_book(cal_id, name, slot_data["start"], slot_data["end"],
                       f"Table for {party_size}")
    logger.info(f"[restaurant tool] book_appointment → {name} party of {party_size} at {slot_label}")
    await params.result_callback(
        f"Reservation confirmed for {name}, party of {party_size}, on {slot_label}."
    )


async def handle_take_message(params: FunctionCallParams) -> None:
    args = params.arguments
    caller_name = args.get("caller_name", "Guest")
    message = args.get("message", "")
    callback = args.get("callback_number", "")
    record = {"caller": caller_name, "message": message, "callback": callback,
              "timestamp": datetime.now().isoformat()}
    _ORDERS.append(record)
    logger.info(f"[restaurant tool] take_message → {json.dumps(record)}")
    result = f"Got it, recorded for {caller_name}."
    if callback:
        result += f" We'll call back at {callback}."
    await params.result_callback(result)


async def handle_transfer_to_human(params: FunctionCallParams) -> None:
    reason = params.arguments.get("reason", "caller request")
    logger.info(f"[restaurant tool] transfer_to_human — {reason}")
    await params.result_callback("Connecting you to a manager now.")


check_availability_schema = FunctionSchema(
    name="check_availability",
    description="Check open reservation times at the restaurant.",
    properties={},
    required=[],
)

book_appointment_schema = FunctionSchema(
    name="book_appointment",
    description="Reserve a table. Call after confirming caller name, party size, and time.",
    properties={
        "patient_name": {"type": "string", "description": "Name for the reservation."},
        "slot": {"type": "string", "description": "The reservation time, e.g. 'Friday June 13 at 7pm'."},
        "service": {"type": "string", "description": "Party size, e.g. '4'."},
    },
    required=["patient_name", "slot", "service"],
)

take_message_schema = FunctionSchema(
    name="take_message",
    description="Record a takeout order, special request, or callback message.",
    properties={
        "caller_name": {"type": "string", "description": "Name of the caller."},
        "message": {"type": "string", "description": "The order or message."},
        "callback_number": {"type": "string", "description": "Phone number for callback (optional)."},
    },
    required=["caller_name", "message"],
)

transfer_to_human_schema = FunctionSchema(
    name="transfer_to_human",
    description="Transfer the caller to a manager.",
    properties={
        "reason": {"type": "string", "description": "Reason for the transfer."},
        "urgency": {"type": "string", "enum": ["normal", "emergency"]},
    },
    required=["reason", "urgency"],
)

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
