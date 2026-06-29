"""
Mock External APIs
==================
Simulates the third-party integrations a real commercial loan processor hits.
In production each function is a REST call to:
  - Experian / Equifax / TransUnion  (credit)
  - LexisNexis / GIACT               (fraud)
  - IRS e-Services                   (tax transcripts)
  - Secretary of State APIs          (business verification)

Each function is async and sleeps briefly to simulate real network latency.
The parallel_checks node fires all four simultaneously — demo shows the
fan-out pattern clearly vs. sequential tool calls in a single agent.
"""

import asyncio
import random
from datetime import datetime, timedelta


async def pull_credit_report(customer_id: str, requested_amount: float) -> dict:
    """Simulates an Experian commercial credit pull (~1-2s in production)."""
    await asyncio.sleep(1.2)

    # Deterministic scores based on customer_id for repeatable demos
    score_map = {
        "CUST-001": 780,   # James Carter — strong
        "CUST-002": 610,   # Maria Chen — borderline
    }
    score = score_map.get(customer_id, random.randint(550, 800))

    if score >= 720:
        summary = "Excellent credit history. No derogatory marks. Low utilization."
    elif score >= 660:
        summary = "Good credit. One 30-day late payment 18 months ago. Utilization 42%."
    else:
        summary = "Fair credit. Two late payments in past 24 months. High utilization 78%."

    return {
        "credit_score": score,
        "credit_report_summary": summary,
    }


async def check_fraud_score(customer_id: str, business_ein: str) -> dict:
    """Simulates LexisNexis identity + business fraud screening (~0.8s)."""
    await asyncio.sleep(0.8)

    score_map = {
        "CUST-001": 0.05,   # very low risk
        "CUST-002": 0.18,   # low-moderate risk
    }
    score = score_map.get(customer_id, round(random.uniform(0.02, 0.35), 2))

    flags = []
    if score > 0.25:
        flags.append("Address mismatch on file")
    if score > 0.40:
        flags.append("EIN registered < 6 months ago")

    return {
        "fraud_score": score,
        "fraud_flags": flags,
    }


async def verify_business(business_ein: str) -> dict:
    """Simulates Secretary of State business entity lookup (~1.0s)."""
    await asyncio.sleep(1.0)

    # Treat any EIN that starts with "12" as unverified for demo
    if business_ein.startswith("12"):
        return {
            "business_verified": False,
            "business_state": None,
            "business_incorporation_date": None,
        }

    years_ago = random.randint(2, 15)
    inc_date = (datetime.now() - timedelta(days=years_ago * 365)).strftime("%Y-%m-%d")
    return {
        "business_verified": True,
        "business_state": "TX",
        "business_incorporation_date": inc_date,
    }


async def pull_tax_transcripts(customer_id: str) -> dict:
    """Simulates IRS e-Services transcript request (~1.5s)."""
    await asyncio.sleep(1.5)

    revenue_map = {
        "CUST-001": 1_250_000.0,
        "CUST-002": 380_000.0,
    }
    revenue = revenue_map.get(customer_id, round(random.uniform(200_000, 2_000_000), 2))

    return {
        "tax_transcripts_received": True,
        "annual_revenue": revenue,
    }
