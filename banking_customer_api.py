"""
Dummy Banking Customer API
==========================
In-memory store simulating a core banking system.
In production this would be REST calls to Temenos / FIS / Finacle.

Exposed as a module (not a service) so banking_tools.py can import it directly.
Swap the implementations here to hit a real API without touching the tools.
"""

from datetime import datetime, timedelta
import random

# ---------------------------------------------------------------------------
# In-memory "database"
# ---------------------------------------------------------------------------

_CUSTOMERS: dict[str, dict] = {
    "4111222233334444": {
        "customer_id": "CUST-001",
        "name": "James Carter",
        "phone_last4": "7890",
        "accounts": {
            "CHK-8821": {
                "type": "Checking",
                "balance": 3_247.58,
                "available": 3_097.58,
                "currency": "USD",
            },
            "SAV-1143": {
                "type": "Savings",
                "balance": 12_850.00,
                "available": 12_850.00,
                "currency": "USD",
            },
        },
        # credit_cards: balance = amount currently owed (positive = you owe money)
        "credit_cards": {
            "CC-4001": {
                "nickname": "Platinum Rewards Visa",
                "last4": "4001",
                "balance_owed": 1_840.75,   # statement balance
                "minimum_due": 37.00,
                "due_date": (datetime.now() + timedelta(days=12)).strftime("%b %d"),
                "credit_limit": 8_000.00,
            },
            "CC-4002": {
                "nickname": "Cash Back Mastercard",
                "last4": "4002",
                "balance_owed": 342.10,
                "minimum_due": 25.00,
                "due_date": (datetime.now() + timedelta(days=5)).strftime("%b %d"),
                "credit_limit": 5_000.00,
            },
        },
        "cards": ["4111222233334444"],
    },
    "5500111122223333": {
        "customer_id": "CUST-002",
        "name": "Maria Chen",
        "phone_last4": "4567",
        "accounts": {
            "CHK-5512": {
                "type": "Checking",
                "balance": 987.23,
                "available": 737.23,
                "currency": "USD",
            },
            "SAV-7790": {
                "type": "Savings",
                "balance": 5_400.00,
                "available": 5_400.00,
                "currency": "USD",
            },
        },
        "credit_cards": {
            "CC-5001": {
                "nickname": "Travel Rewards Visa",
                "last4": "5001",
                "balance_owed": 620.00,
                "minimum_due": 25.00,
                "due_date": (datetime.now() + timedelta(days=8)).strftime("%b %d"),
                "credit_limit": 6_000.00,
            },
        },
        "cards": ["5500111122223333"],
    },
}

# card_number → list of recent transactions (newest first)
_TRANSACTIONS: dict[str, list[dict]] = {
    "4111222233334444": [
        {"date": (datetime.now() - timedelta(days=1)).strftime("%b %d"), "description": "Whole Foods Market", "amount": -64.38, "account": "CHK-8821"},
        {"date": (datetime.now() - timedelta(days=2)).strftime("%b %d"), "description": "Netflix", "amount": -15.99, "account": "CHK-8821"},
        {"date": (datetime.now() - timedelta(days=3)).strftime("%b %d"), "description": "Direct Deposit - Payroll", "amount": 2_800.00, "account": "CHK-8821"},
        {"date": (datetime.now() - timedelta(days=4)).strftime("%b %d"), "description": "Shell Gas Station", "amount": -52.10, "account": "CHK-8821"},
        {"date": (datetime.now() - timedelta(days=5)).strftime("%b %d"), "description": "Amazon", "amount": -38.99, "account": "CHK-8821"},
    ],
    "5500111122223333": [
        {"date": (datetime.now() - timedelta(days=1)).strftime("%b %d"), "description": "Starbucks", "amount": -6.75, "account": "CHK-5512"},
        {"date": (datetime.now() - timedelta(days=2)).strftime("%b %d"), "description": "Uber", "amount": -22.40, "account": "CHK-5512"},
        {"date": (datetime.now() - timedelta(days=3)).strftime("%b %d"), "description": "Direct Deposit", "amount": 1_500.00, "account": "CHK-5512"},
    ],
}

# pending payments keued during calls: list of dicts
_PAYMENT_LOG: list[dict] = []


# ---------------------------------------------------------------------------
# Public API functions
# ---------------------------------------------------------------------------

def authenticate_customer(card_last4: str, phone_last4: str) -> dict | None:
    """
    Authenticate by last 4 digits of card + last 4 of phone.
    Returns customer dict on success, None on failure.
    Demo cards: 4444 (James Carter, phone 7890), 3333 (Maria Chen, phone 4567).
    """
    for card_number, customer in _CUSTOMERS.items():
        if card_number.endswith(card_last4) and customer["phone_last4"] == phone_last4:
            return {
                "customer_id": customer["customer_id"],
                "name": customer["name"],
                "card_number": card_number,
                "accounts": customer["accounts"],
            }
    return None


def get_balances(card_number: str) -> list[dict]:
    """Return all account balances for an authenticated customer."""
    customer = _CUSTOMERS.get(card_number)
    if not customer:
        return []
    result = []
    for acct_id, acct in customer["accounts"].items():
        result.append({
            "account_id": acct_id,
            "type": acct["type"],
            "balance": acct["balance"],
            "available": acct["available"],
            "currency": acct["currency"],
        })
    return result


def get_recent_transactions(card_number: str, count: int = 5) -> list[dict]:
    """Return the N most recent transactions."""
    return _TRANSACTIONS.get(card_number, [])[:count]


def get_credit_cards(card_number: str) -> list[dict]:
    """Return all credit cards on file for an authenticated customer."""
    customer = _CUSTOMERS.get(card_number)
    if not customer:
        return []
    result = []
    for cc_id, cc in customer.get("credit_cards", {}).items():
        result.append({
            "card_id": cc_id,
            "nickname": cc["nickname"],
            "last4": cc["last4"],
            "balance_owed": cc["balance_owed"],
            "minimum_due": cc["minimum_due"],
            "due_date": cc["due_date"],
            "credit_limit": cc["credit_limit"],
        })
    return result


def _resolve_credit_card(customer: dict, identifier: str) -> tuple[str, dict] | tuple[None, None]:
    """
    Find a credit card by card_id, last4, or nickname fragment (case-insensitive).
    Returns (card_id, card_dict) or (None, None).
    """
    credit_cards = customer.get("credit_cards", {})
    identifier = identifier.strip()

    # Exact card_id match
    if identifier in credit_cards:
        return identifier, credit_cards[identifier]

    # Match by last4
    for cc_id, cc in credit_cards.items():
        if cc["last4"] == identifier:
            return cc_id, cc

    # Match by nickname fragment
    for cc_id, cc in credit_cards.items():
        if identifier.lower() in cc["nickname"].lower():
            return cc_id, cc

    return None, None


def pay_credit_card(
    card_number: str,
    credit_card_identifier: str,
    from_account: str,
    amount: float,
) -> dict:
    """
    Pay a credit card balance from a deposit account.

    credit_card_identifier: card_id (CC-4001), last4 ("4001"), or nickname fragment ("Platinum").
    from_account: account_id, or type keyword like "checking" / "savings".

    Returns {"success": True, ...} or {"success": False, "reason": "..."}
    """
    customer = _CUSTOMERS.get(card_number)
    if not customer:
        return {"success": False, "reason": "Customer not found."}

    # Resolve source deposit account
    account = customer["accounts"].get(from_account)
    if not account:
        for acct_id, acct in customer["accounts"].items():
            if from_account.lower() in acct["type"].lower():
                account = acct
                from_account = acct_id
                break
    if not account:
        return {"success": False, "reason": f"Source account '{from_account}' not found."}

    # Resolve target credit card
    cc_id, credit_card = _resolve_credit_card(customer, credit_card_identifier)
    if not credit_card:
        return {"success": False, "reason": f"Credit card '{credit_card_identifier}' not found on your account."}

    if amount <= 0:
        return {"success": False, "reason": "Payment amount must be greater than zero."}

    if account["available"] < amount:
        return {
            "success": False,
            "reason": f"Insufficient funds in your {account['type']} account. Available: ${account['available']:,.2f}.",
        }

    if amount > credit_card["balance_owed"]:
        return {
            "success": False,
            "reason": (
                f"Payment of ${amount:,.2f} exceeds the current balance of "
                f"${credit_card['balance_owed']:,.2f} on your {credit_card['nickname']} card. "
                f"Would you like to pay the full balance instead?"
            ),
        }

    # Apply payment
    account["balance"] -= amount
    account["available"] -= amount
    credit_card["balance_owed"] -= amount
    if credit_card["balance_owed"] < credit_card["minimum_due"]:
        credit_card["minimum_due"] = max(0, credit_card["balance_owed"])

    reference = f"CCP-{random.randint(100000, 999999)}"
    record = {
        "reference": reference,
        "date": datetime.now().strftime("%b %d"),
        "description": f"Credit Card Payment - {credit_card['nickname']} ending {credit_card['last4']}",
        "amount": -amount,
        "account": from_account,
    }
    _PAYMENT_LOG.append({**record, "card_number": card_number, "credit_card_id": cc_id})
    _TRANSACTIONS.setdefault(card_number, []).insert(0, record)

    return {
        "success": True,
        "reference": reference,
        "credit_card_nickname": credit_card["nickname"],
        "credit_card_last4": credit_card["last4"],
        "amount_paid": amount,
        "remaining_balance": credit_card["balance_owed"],
        "new_deposit_balance": account["balance"],
        "from_account": from_account,
    }


def make_payment(card_number: str, from_account: str, payee: str, amount: float) -> dict:
    """
    Debit from_account and record payment.
    Returns {"success": True, "reference": "...", "new_balance": ...}
    or      {"success": False, "reason": "..."}
    """
    customer = _CUSTOMERS.get(card_number)
    if not customer:
        return {"success": False, "reason": "Customer not found."}

    account = customer["accounts"].get(from_account)
    if not account:
        # Try fuzzy match on type (e.g. "checking" → CHK-*)
        for acct_id, acct in customer["accounts"].items():
            if from_account.lower() in acct["type"].lower():
                account = acct
                from_account = acct_id
                break
    if not account:
        return {"success": False, "reason": f"Account '{from_account}' not found."}

    if account["available"] < amount:
        return {
            "success": False,
            "reason": f"Insufficient funds. Available balance is ${account['available']:,.2f}.",
        }

    # Debit
    account["balance"] -= amount
    account["available"] -= amount

    reference = f"PAY-{random.randint(100000, 999999)}"
    record = {
        "reference": reference,
        "date": datetime.now().strftime("%b %d"),
        "description": f"Payment to {payee}",
        "amount": -amount,
        "account": from_account,
    }
    _PAYMENT_LOG.append({**record, "card_number": card_number})
    _TRANSACTIONS.setdefault(card_number, []).insert(0, record)

    return {
        "success": True,
        "reference": reference,
        "payee": payee,
        "amount": amount,
        "new_balance": account["balance"],
        "account": from_account,
    }
