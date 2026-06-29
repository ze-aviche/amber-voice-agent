"""
LangGraph Nodes — Commercial Loan Processing
============================================
Each function is one node in the graph. Nodes receive the full state,
do their work, and return a PARTIAL state dict — LangGraph merges it.

Node execution order (enforced by graph edges, not by the LLM):
  kyc_verification
      ↓
  parallel_checks          ← fires credit + fraud + business + tax simultaneously
      ↓
  underwriting_rules        ← auto approve / auto decline / manual review
      ↓ (manual path)
  underwriter_review        ← INTERRUPT: graph pauses, waits for human input
      ↓
  offer_generation  OR  adverse_action_notice
"""

import asyncio
from datetime import datetime, timezone

from loguru import logger

from loan.mock_apis import (
    pull_credit_report,
    check_fraud_score,
    verify_business,
    pull_tax_transcripts,
)
from loan.state import LoanApplicationState


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Node 1: KYC Verification ─────────────────────────────────────────────────

async def kyc_verification(state: LoanApplicationState) -> dict:
    """
    Verify the applicant's identity before touching any financial data.
    ECOA disclosure is stamped here — legally required before credit pull.
    """
    logger.info(f"[loan:{state['application_id']}] NODE: kyc_verification")

    # In production: hit a KYC provider (Socure, Jumio, LexisNexis)
    # For demo: anyone with a valid customer_id passes
    kyc_passed = state["customer_id"].startswith("CUST-")

    if not kyc_passed:
        return {
            "current_node": "kyc_verification",
            "kyc_status": "failed",
            "kyc_failure_reason": "Identity could not be verified against government records.",
            "adverse_action_sent": False,
        }

    logger.info(f"[loan:{state['application_id']}] KYC passed — stamping ECOA disclosure")
    return {
        "current_node": "kyc_verification",
        "kyc_status": "passed",
        "kyc_failure_reason": None,
        # ECOA must be stamped before credit pull — graph edge enforces this
        "ecoa_disclosed_at": _now(),
        "adverse_action_sent": False,
    }


# ── Node 2: Parallel External Checks ────────────────────────────────────────

async def parallel_checks(state: LoanApplicationState) -> dict:
    """
    Fan-out: fire all four external checks simultaneously.
    Total time = slowest single check (~1.5s), NOT sum of all four (~4.5s).

    This is the key LangGraph demo point — a single agent calling these
    tools sequentially would take 3x longer.
    """
    logger.info(f"[loan:{state['application_id']}] NODE: parallel_checks — fanning out 4 checks")
    t_start = asyncio.get_event_loop().time()

    credit_result, fraud_result, biz_result, tax_result = await asyncio.gather(
        pull_credit_report(state["customer_id"], state["requested_amount"]),
        check_fraud_score(state["customer_id"], state["business_ein"]),
        verify_business(state["business_ein"]),
        pull_tax_transcripts(state["customer_id"]),
    )

    elapsed = asyncio.get_event_loop().time() - t_start
    logger.info(
        f"[loan:{state['application_id']}] parallel_checks done in {elapsed:.1f}s "
        f"(credit={credit_result['credit_score']}, fraud={fraud_result['fraud_score']:.2f})"
    )

    return {
        "current_node": "parallel_checks",
        **credit_result,
        **fraud_result,
        **biz_result,
        **tax_result,
    }


# ── Node 3: Underwriting Rules Engine ────────────────────────────────────────

async def underwriting_rules(state: LoanApplicationState) -> dict:
    """
    Apply deterministic rules to reach an auto decision or flag for manual review.
    Rules are explicit code — not LLM reasoning — because compliance requires
    100% auditability of every credit decision (ECOA, FCRA).
    """
    logger.info(f"[loan:{state['application_id']}] NODE: underwriting_rules")

    score = state.get("credit_score", 0)
    fraud = state.get("fraud_score", 1.0)
    revenue = state.get("annual_revenue", 0)
    amount = state["requested_amount"]
    biz_verified = state.get("business_verified", False)

    decline_reasons = []

    # Hard declines — any one of these → auto decline
    if score < 580:
        decline_reasons.append(f"Credit score {score} is below minimum threshold of 580.")
    if fraud > 0.50:
        decline_reasons.append(f"Fraud risk score {fraud:.2f} exceeds maximum of 0.50.")
    if not biz_verified:
        decline_reasons.append("Business entity could not be verified with Secretary of State.")
    if not state.get("tax_transcripts_received"):
        decline_reasons.append("IRS tax transcripts not received.")

    if decline_reasons:
        logger.info(f"[loan:{state['application_id']}] AUTO DECLINE — {decline_reasons}")
        return {
            "current_node": "underwriting_rules",
            "underwriting_decision": "declined",
            "decline_reasons": decline_reasons,
            "auto_decision_rationale": "One or more hard-decline criteria met.",
        }

    # Debt-service coverage: annual revenue must be >= 1.25x annual loan payments
    # Approximate annual payment: amount / (term_months / 12)
    # Use conservative 60-month term for this check
    approx_annual_payment = (amount / 60) * 12
    dscr = revenue / approx_annual_payment if approx_annual_payment > 0 else 0

    # Auto approve — strong file, no flags
    if score >= 720 and fraud < 0.15 and dscr >= 1.5 and amount <= 250_000:
        logger.info(f"[loan:{state['application_id']}] AUTO APPROVE (score={score}, dscr={dscr:.2f})")
        return {
            "current_node": "underwriting_rules",
            "underwriting_decision": "approved",
            "decline_reasons": [],
            "auto_decision_rationale": (
                f"Auto-approved: credit score {score}, fraud score {fraud:.2f}, "
                f"DSCR {dscr:.2f}, amount within auto-approve limit."
            ),
        }

    # Manual review — borderline file or large loan
    rationale = (
        f"Manual review required: score={score}, fraud={fraud:.2f}, "
        f"dscr={dscr:.2f}, amount=${amount:,.0f}."
    )
    logger.info(f"[loan:{state['application_id']}] MANUAL REVIEW — {rationale}")
    return {
        "current_node": "underwriting_rules",
        "underwriting_decision": "manual_review",
        "decline_reasons": [],
        "auto_decision_rationale": rationale,
    }


# ── Node 4: Underwriter Review (HUMAN INTERRUPT) ──────────────────────────────

async def underwriter_review(state: LoanApplicationState) -> dict:
    """
    The graph PAUSES here and waits for a human underwriter to act.
    This node is registered as an interrupt point in graph.py.

    What happens:
      1. Graph reaches this node and suspends (checkpoints state to DB).
      2. REST API exposes GET /api/loans/{id} — dashboard shows "Pending Review".
      3. Underwriter logs in, reviews the file, clicks Approve or Decline.
      4. POST /api/loans/{id}/decision calls graph.resume() with their input.
      5. Graph picks up exactly here, merges the decision into state, continues.

    This is the interview talking point: the customer isn't on the phone.
    The application might sit here for hours. State persists in SQLite.
    A single voice agent context array has no answer for this.
    """
    logger.info(
        f"[loan:{state['application_id']}] NODE: underwriter_review "
        f"— INTERRUPT, waiting for human decision"
    )

    # When the graph resumes, underwriter_decision will be set in state.
    # This node just records who reviewed it and when.
    decision = state.get("underwriter_decision")
    if not decision:
        # First entry — graph will interrupt before returning
        return {"current_node": "underwriter_review"}

    # Graph resumed with decision — record the timestamp
    logger.info(
        f"[loan:{state['application_id']}] Underwriter decision: {decision} "
        f"by {state.get('underwriter_id', 'unknown')}"
    )
    return {
        "current_node": "underwriter_review",
        "underwriter_decided_at": _now(),
        "underwriting_decision": decision,   # promote to main decision field
    }


# ── Node 5a: Offer Generation ─────────────────────────────────────────────────

async def offer_generation(state: LoanApplicationState) -> dict:
    """
    Generate the loan offer terms based on credit profile.
    In production: pricing engine call (Black Knight, Optimal Blue).
    """
    logger.info(f"[loan:{state['application_id']}] NODE: offer_generation")

    score = state.get("credit_score", 650)
    amount = state["requested_amount"]

    # Rate tiers based on credit score
    if score >= 760:
        rate = 6.25
    elif score >= 720:
        rate = 7.00
    elif score >= 680:
        rate = 8.50
    else:
        rate = 10.25

    term_months = 60
    monthly_rate = rate / 100 / 12
    # Standard amortization formula
    monthly_payment = amount * (monthly_rate * (1 + monthly_rate) ** term_months) / \
                      ((1 + monthly_rate) ** term_months - 1)

    logger.info(
        f"[loan:{state['application_id']}] Offer: ${amount:,.0f} @ {rate}% "
        f"for {term_months}mo = ${monthly_payment:,.2f}/mo"
    )

    return {
        "current_node": "offer_generation",
        "approved_amount": amount,
        "interest_rate": rate,
        "term_months": term_months,
        "monthly_payment": round(monthly_payment, 2),
        "offer_generated_at": _now(),
    }


# ── Node 5b: Adverse Action Notice ────────────────────────────────────────────

async def adverse_action_notice(state: LoanApplicationState) -> dict:
    """
    Send FCRA-required adverse action notice on decline.
    In production: triggers a certified letter + email via DocuSign/Lob.
    30-day window for applicant to request the credit report used.
    """
    logger.info(f"[loan:{state['application_id']}] NODE: adverse_action_notice")

    reasons = state.get("decline_reasons") or ["Credit criteria not met."]
    logger.info(
        f"[loan:{state['application_id']}] Adverse action notice sent — "
        f"reasons: {reasons}"
    )

    return {
        "current_node": "adverse_action_notice",
        "adverse_action_sent": True,
    }
