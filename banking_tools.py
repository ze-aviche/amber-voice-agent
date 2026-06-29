"""
Banking vertical — tool implementations.

Tools:
  authenticate_customer  — verify caller identity (card last4 + phone last4)
  get_account_balance    — return balances for authenticated customer
  get_recent_transactions — last N transactions
  make_payment           — pay a payee from a named account
  transfer_to_human      — escalate to a live agent

Authentication is required before any account tool will execute.
The auth state is stored in app_resources["banking_auth"] during the call.
"""

import json
from datetime import datetime

from loguru import logger
from pipecat.services.llm_service import FunctionCallParams
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema

import banking_customer_api as bank_api


def _get_auth(params: FunctionCallParams) -> dict | None:
    """Return auth record if the caller has authenticated this call, else None."""
    return (params.app_resources or {}).get("banking_auth")


def _require_auth(params: FunctionCallParams) -> str | None:
    """Return an error string if not authenticated, else None."""
    if not _get_auth(params):
        return (
            "I'm sorry, but I need to verify your identity before I can access your account. "
            "Could you please provide the last four digits of your card number?"
        )
    return None


# ---------------------------------------------------------------------------
# Tool: authenticate_customer
# ---------------------------------------------------------------------------

async def handle_authenticate_customer(params: FunctionCallParams) -> None:
    args = params.arguments
    card_last4 = str(args.get("card_last4", "")).strip()
    phone_last4 = str(args.get("phone_last4", "")).strip()

    customer = bank_api.authenticate_customer(card_last4, phone_last4)
    if not customer:
        logger.warning(f"[tool] authenticate_customer — FAILED (card_last4={card_last4})")
        await params.result_callback(
            "Authentication failed. The card number or phone number you provided does not match our records. "
            "Please double-check and try again, or I can connect you to a live agent."
        )
        return

    if params.app_resources is not None:
        params.app_resources["banking_auth"] = customer
        params.app_resources["caller_name"] = customer["name"]

    logger.info(f"[tool] authenticate_customer — OK ({customer['name']})")
    await params.result_callback(
        f"Identity verified. Welcome, {customer['name']}. How can I help you today?"
    )


authenticate_customer_schema = FunctionSchema(
    name="authenticate_customer",
    description=(
        "Verify the caller's identity using the last 4 digits of their debit/credit card "
        "and the last 4 digits of their phone number on file. "
        "Always call this before any account-access tool."
    ),
    properties={
        "card_last4": {
            "type": "string",
            "description": "Last 4 digits of the caller's card number.",
        },
        "phone_last4": {
            "type": "string",
            "description": "Last 4 digits of the phone number registered on the account.",
        },
    },
    required=["card_last4", "phone_last4"],
)


# ---------------------------------------------------------------------------
# Tool: get_account_balance
# ---------------------------------------------------------------------------

async def handle_get_account_balance(params: FunctionCallParams) -> None:
    err = _require_auth(params)
    if err:
        await params.result_callback(err)
        return

    auth = _get_auth(params)
    balances = bank_api.get_balances(auth["card_number"])

    if not balances:
        await params.result_callback("I was unable to retrieve your account balances. Please try again.")
        return

    parts = []
    for acct in balances:
        parts.append(
            f"{acct['type']} account ending {acct['account_id'][-4:]}: "
            f"balance ${acct['balance']:,.2f}, available ${acct['available']:,.2f}"
        )

    result = "Here are your current balances. " + ". ".join(parts) + "."
    logger.info(f"[tool] get_account_balance → {result}")
    await params.result_callback(result)


get_account_balance_schema = FunctionSchema(
    name="get_account_balance",
    description="Retrieve current and available balances for all accounts of the authenticated caller.",
    properties={},
    required=[],
)


# ---------------------------------------------------------------------------
# Tool: get_recent_transactions
# ---------------------------------------------------------------------------

async def handle_get_recent_transactions(params: FunctionCallParams) -> None:
    err = _require_auth(params)
    if err:
        await params.result_callback(err)
        return

    auth = _get_auth(params)
    count = int(params.arguments.get("count", 5))
    txns = bank_api.get_recent_transactions(auth["card_number"], count=count)

    if not txns:
        await params.result_callback("No recent transactions found.")
        return

    parts = []
    for t in txns:
        sign = "+" if t["amount"] > 0 else ""
        parts.append(f"{t['date']}: {t['description']}, {sign}${abs(t['amount']):.2f}")

    result = f"Your {len(txns)} most recent transactions are: " + "; ".join(parts) + "."
    logger.info(f"[tool] get_recent_transactions → {len(txns)} items")
    await params.result_callback(result)


get_recent_transactions_schema = FunctionSchema(
    name="get_recent_transactions",
    description="Retrieve the caller's most recent transactions. Requires authentication.",
    properties={
        "count": {
            "type": "integer",
            "description": "Number of transactions to return (default 5, max 10).",
        },
    },
    required=[],
)


# ---------------------------------------------------------------------------
# Tool: make_payment
# ---------------------------------------------------------------------------

async def handle_make_payment(params: FunctionCallParams) -> None:
    err = _require_auth(params)
    if err:
        await params.result_callback(err)
        return

    auth = _get_auth(params)
    args = params.arguments
    from_account = str(args.get("from_account", "checking")).strip()
    payee = str(args.get("payee", "")).strip()
    amount = float(args.get("amount", 0))

    if amount <= 0:
        await params.result_callback("The payment amount must be greater than zero.")
        return
    if not payee:
        await params.result_callback("Please tell me who you'd like to pay.")
        return

    result = bank_api.make_payment(auth["card_number"], from_account, payee, amount)

    if not result["success"]:
        logger.warning(f"[tool] make_payment FAILED — {result['reason']}")
        await params.result_callback(result["reason"])
        return

    if params.app_resources is not None:
        params.app_resources["outcome"] = "booked"   # reuse "booked" = successful transaction

    msg = (
        f"Payment of ${amount:,.2f} to {payee} has been processed successfully. "
        f"Your reference number is {result['reference']}. "
        f"Your new balance is ${result['new_balance']:,.2f}."
    )
    logger.info(f"[tool] make_payment OK → ref={result['reference']}")
    await params.result_callback(msg)


make_payment_schema = FunctionSchema(
    name="make_payment",
    description=(
        "Make a bill payment or transfer from the caller's account to a payee. "
        "Always confirm the payee name and amount with the caller before calling this tool."
    ),
    properties={
        "from_account": {
            "type": "string",
            "description": "Account to debit: 'checking' or 'savings', or the account ID like 'CHK-8821'.",
        },
        "payee": {
            "type": "string",
            "description": "Name of the payee or biller (e.g. 'AT&T', 'Electric Company').",
        },
        "amount": {
            "type": "number",
            "description": "Dollar amount to pay.",
        },
    },
    required=["from_account", "payee", "amount"],
)


# ---------------------------------------------------------------------------
# Tool: get_credit_cards
# ---------------------------------------------------------------------------

async def handle_get_credit_cards(params: FunctionCallParams) -> None:
    err = _require_auth(params)
    if err:
        await params.result_callback(err)
        return

    auth = _get_auth(params)
    cards = bank_api.get_credit_cards(auth["card_number"])

    if not cards:
        await params.result_callback("I don't see any credit cards linked to your account.")
        return

    parts = []
    for cc in cards:
        parts.append(
            f"{cc['nickname']} ending in {cc['last4']}: "
            f"balance owed ${cc['balance_owed']:,.2f}, "
            f"minimum due ${cc['minimum_due']:,.2f} by {cc['due_date']}"
        )

    result = f"You have {len(cards)} credit card{'s' if len(cards) > 1 else ''} on file. " + ". ".join(parts) + "."
    logger.info(f"[tool] get_credit_cards → {len(cards)} cards")
    await params.result_callback(result)


get_credit_cards_schema = FunctionSchema(
    name="get_credit_cards",
    description=(
        "List all credit cards linked to the authenticated customer's account, "
        "including current balance owed, minimum payment due, and due date. "
        "Call this when the customer asks about their credit cards or before taking a credit card payment."
    ),
    properties={},
    required=[],
)


# ---------------------------------------------------------------------------
# Tool: pay_credit_card
# ---------------------------------------------------------------------------

async def handle_pay_credit_card(params: FunctionCallParams) -> None:
    err = _require_auth(params)
    if err:
        await params.result_callback(err)
        return

    auth = _get_auth(params)
    args = params.arguments
    credit_card_identifier = str(args.get("credit_card", "")).strip()
    from_account = str(args.get("from_account", "checking")).strip()
    amount = float(args.get("amount", 0))

    if not credit_card_identifier:
        await params.result_callback(
            "Which credit card would you like to make a payment to? "
            "You can say the card nickname or the last four digits."
        )
        return

    if amount <= 0:
        await params.result_callback("Please tell me the amount you'd like to pay.")
        return

    result = bank_api.pay_credit_card(
        auth["card_number"], credit_card_identifier, from_account, amount
    )

    if not result["success"]:
        logger.warning(f"[tool] pay_credit_card FAILED — {result['reason']}")
        await params.result_callback(result["reason"])
        return

    if params.app_resources is not None:
        params.app_resources["outcome"] = "booked"

    msg = (
        f"Your payment of ${result['amount_paid']:,.2f} to your "
        f"{result['credit_card_nickname']} card ending in {result['credit_card_last4']} "
        f"has been processed. Reference number: {' '.join(result['reference'])}. "
        f"Your remaining credit card balance is ${result['remaining_balance']:,.2f}."
    )
    logger.info(f"[tool] pay_credit_card OK → ref={result['reference']}")
    await params.result_callback(msg)


pay_credit_card_schema = FunctionSchema(
    name="pay_credit_card",
    description=(
        "Make a payment toward a credit card balance using funds from a deposit account. "
        "Always call get_credit_cards first if the customer has not specified which card. "
        "Confirm the card, amount, and source account with the customer before calling this tool."
    ),
    properties={
        "credit_card": {
            "type": "string",
            "description": (
                "Which credit card to pay. Accept the card nickname, last 4 digits, "
                "or internal card ID (e.g. 'Platinum', '4001', 'CC-4001')."
            ),
        },
        "from_account": {
            "type": "string",
            "description": "Source deposit account to pay from: 'checking', 'savings', or account ID like 'CHK-8821'.",
        },
        "amount": {
            "type": "number",
            "description": "Dollar amount to pay toward the credit card balance.",
        },
    },
    required=["credit_card", "from_account", "amount"],
)


# ---------------------------------------------------------------------------
# Tool: transfer_to_human
# ---------------------------------------------------------------------------

async def handle_transfer_to_human(params: FunctionCallParams) -> None:
    args = params.arguments
    reason = args.get("reason", "caller request")
    urgency = args.get("urgency", "normal")

    if params.app_resources is not None:
        params.app_resources["outcome"] = "transfer"

    if urgency == "fraud":
        result = "FRAUD_TRANSFER: connecting to the Fraud Prevention team immediately."
        logger.warning(f"[tool] FRAUD escalation — reason: {reason}")
    else:
        result = "TRANSFER: connecting you to a live banking specialist now."
        logger.info(f"[tool] transfer_to_human — reason: {reason}")

    await params.result_callback(result)


transfer_to_human_schema = FunctionSchema(
    name="transfer_to_human",
    description=(
        "Transfer the caller to a live banking agent. "
        "Use urgency='fraud' for suspected fraud or unauthorized transactions. "
        "Use urgency='normal' when the caller requests a human or has a complex issue."
    ),
    properties={
        "reason": {"type": "string", "description": "Brief reason for the transfer."},
        "urgency": {
            "type": "string",
            "enum": ["normal", "fraud"],
            "description": "'fraud' for fraud/unauthorized activity, 'normal' otherwise.",
        },
    },
    required=["reason", "urgency"],
)


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

TOOLS_SCHEMA = ToolsSchema(standard_tools=[
    authenticate_customer_schema,
    get_account_balance_schema,
    get_recent_transactions_schema,
    get_credit_cards_schema,
    make_payment_schema,
    pay_credit_card_schema,
    transfer_to_human_schema,
])

TOOL_HANDLERS = {
    "authenticate_customer": handle_authenticate_customer,
    "get_account_balance": handle_get_account_balance,
    "get_recent_transactions": handle_get_recent_transactions,
    "get_credit_cards": handle_get_credit_cards,
    "make_payment": handle_make_payment,
    "pay_credit_card": handle_pay_credit_card,
    "transfer_to_human": handle_transfer_to_human,
}
