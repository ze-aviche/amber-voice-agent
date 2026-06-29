"""
LangGraph — Commercial Loan Processing Graph
============================================
Assembles nodes into a directed graph with:
  - Conditional edges (route by underwriting decision)
  - Human interrupt at underwriter_review
  - AsyncSqliteSaver checkpointer (state survives restarts)

The graph is compiled once at module import and reused across all applications.
Each application is a separate "thread" identified by application_id.

Key LangGraph concepts demonstrated:
  - StateGraph: the typed graph container
  - add_node / add_edge / add_conditional_edges: graph topology
  - interrupt_before: suspend graph at a node, await external input
  - AsyncSqliteSaver: async persistent checkpointing
  - graph.astream(): async generator yielding state after each node
  - graph.update_state(): inject external input (underwriter decision) to resume
"""

import sqlite3
from pathlib import Path

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from loan.state import LoanApplicationState
from loan.nodes import (
    kyc_verification,
    parallel_checks,
    underwriting_rules,
    underwriter_review,
    offer_generation,
    adverse_action_notice,
)

_DB_PATH = str(Path("loan_checkpoints.db"))

# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------

def route_after_kyc(state: LoanApplicationState) -> str:
    if state["kyc_status"] == "failed":
        return "adverse_action_notice"
    return "parallel_checks"


def route_after_underwriting(state: LoanApplicationState) -> str:
    decision = state.get("underwriting_decision")
    if decision == "approved":
        return "offer_generation"
    if decision == "declined":
        return "adverse_action_notice"
    return "underwriter_review"


def route_after_human(state: LoanApplicationState) -> str:
    if state.get("underwriter_decision") == "approved":
        return "offer_generation"
    return "adverse_action_notice"


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def _build_graph(checkpointer: AsyncSqliteSaver):
    graph = StateGraph(LoanApplicationState)

    graph.add_node("kyc_verification",      kyc_verification)
    graph.add_node("parallel_checks",       parallel_checks)
    graph.add_node("underwriting_rules",    underwriting_rules)
    graph.add_node("underwriter_review",    underwriter_review)
    graph.add_node("offer_generation",      offer_generation)
    graph.add_node("adverse_action_notice", adverse_action_notice)

    graph.add_edge(START, "kyc_verification")
    graph.add_conditional_edges("kyc_verification",   route_after_kyc)
    graph.add_edge("parallel_checks", "underwriting_rules")
    graph.add_conditional_edges("underwriting_rules", route_after_underwriting)
    graph.add_conditional_edges("underwriter_review", route_after_human)
    graph.add_edge("offer_generation",      END)
    graph.add_edge("adverse_action_notice", END)

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["underwriter_review"],
    )


# ---------------------------------------------------------------------------
# Singleton checkpointer + compiled graph
# Checkpointer is created as a context manager in production;
# for simplicity we open it once at module level.
# ---------------------------------------------------------------------------

import aiosqlite as _aiosqlite

async def _make_graph():
    conn = await _aiosqlite.connect(_DB_PATH)
    checkpointer = AsyncSqliteSaver(conn)
    return _build_graph(checkpointer), checkpointer

# Lazy-init: graph is created on first use inside an async context
_graph_instance = None
_checkpointer_instance = None


async def get_loan_graph():
    global _graph_instance, _checkpointer_instance
    if _graph_instance is None:
        _graph_instance, _checkpointer_instance = await _make_graph()
    return _graph_instance


# ---------------------------------------------------------------------------
# Helper functions used by api.py
# ---------------------------------------------------------------------------

async def get_application_state(application_id: str) -> dict | None:
    graph = await get_loan_graph()
    config = {"configurable": {"thread_id": application_id}}
    snapshot = await graph.aget_state(config)
    if not snapshot or not snapshot.values:
        return None
    state = dict(snapshot.values)
    state["_next_nodes"] = list(snapshot.next) if snapshot.next else []
    state["_is_interrupted"] = "underwriter_review" in (snapshot.next or [])
    return state


async def list_applications() -> list[dict]:
    try:
        conn = sqlite3.connect(_DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id"
        ).fetchall()
        conn.close()
    except Exception:
        return []

    results = []
    for row in rows:
        app_id = row["thread_id"]
        state = await get_application_state(app_id)
        if state:
            results.append({
                "application_id": app_id,
                "customer_name":        state.get("customer_name"),
                "business_name":        state.get("business_name"),
                "requested_amount":     state.get("requested_amount"),
                "current_node":         state.get("current_node"),
                "underwriting_decision":state.get("underwriting_decision"),
                "underwriter_decision": state.get("underwriter_decision"),
                "is_interrupted":       state.get("_is_interrupted", False),
                "offer_generated_at":   state.get("offer_generated_at"),
                "adverse_action_sent":  state.get("adverse_action_sent", False),
                "kyc_status":           state.get("kyc_status"),
                "credit_score":         state.get("credit_score"),
                "fraud_score":          state.get("fraud_score"),
                "annual_revenue":       state.get("annual_revenue"),
                "auto_decision_rationale": state.get("auto_decision_rationale"),
                "decline_reasons":      state.get("decline_reasons"),
                "credit_report_summary":state.get("credit_report_summary"),
                "fraud_flags":          state.get("fraud_flags"),
                "business_verified":    state.get("business_verified"),
                "business_state":       state.get("business_state"),
                "approved_amount":      state.get("approved_amount"),
                "interest_rate":        state.get("interest_rate"),
                "term_months":          state.get("term_months"),
                "monthly_payment":      state.get("monthly_payment"),
            })
    return results
