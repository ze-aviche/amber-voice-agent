"""
Loan Application State
======================
The single source of truth that flows through every node in the LangGraph.
Checkpointed to SQLite after every node — survives restarts, handoffs, crashes.

This is the interview demo centerpiece: explicit, typed, auditable state
that a single-agent context array could never maintain across days/sessions.
"""

from typing import Literal, Optional
from typing_extensions import TypedDict


class LoanApplicationState(TypedDict):
    # ── Application identity ─────────────────────────────────────────────────
    application_id: str
    customer_id: str
    customer_name: str
    business_name: str
    business_ein: str          # Employer Identification Number
    requested_amount: float
    loan_purpose: str
    started_at: str

    # ── KYC / Identity verification ──────────────────────────────────────────
    kyc_status: Literal["pending", "passed", "failed"]
    kyc_failure_reason: Optional[str]

    # ── Parallel external checks (all run simultaneously) ────────────────────
    credit_score: Optional[int]
    credit_report_summary: Optional[str]

    fraud_score: Optional[float]       # 0.0 (clean) → 1.0 (high risk)
    fraud_flags: Optional[list]

    business_verified: Optional[bool]
    business_state: Optional[str]
    business_incorporation_date: Optional[str]

    tax_transcripts_received: Optional[bool]
    annual_revenue: Optional[float]    # extracted from tax transcripts

    # ── Underwriting decision ─────────────────────────────────────────────────
    underwriting_decision: Optional[Literal["approved", "declined", "manual_review"]]
    decline_reasons: Optional[list]
    auto_decision_rationale: Optional[str]

    # ── Human-in-the-loop gate ────────────────────────────────────────────────
    underwriter_id: Optional[str]
    underwriter_notes: Optional[str]
    underwriter_decision: Optional[Literal["approved", "declined"]]
    underwriter_decided_at: Optional[str]

    # ── Offer ─────────────────────────────────────────────────────────────────
    approved_amount: Optional[float]
    interest_rate: Optional[float]     # annual percentage rate
    term_months: Optional[int]
    monthly_payment: Optional[float]
    offer_generated_at: Optional[str]

    # ── Compliance stamps (ordering enforced by graph edges) ─────────────────
    ecoa_disclosed_at: Optional[str]   # Equal Credit Opportunity Act — must precede credit pull
    adverse_action_sent: bool          # FCRA requirement on decline

    # ── Resumption tracking ───────────────────────────────────────────────────
    current_node: str                  # which node we're at — for dashboard display
    session_count: int                 # how many separate calls/sessions this has taken
    error_message: Optional[str]       # set if a node fails, displayed in dashboard
