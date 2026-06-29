"""
Real-time sentiment analysis for live calls.

Uses Claude Haiku to score the last N conversation turns.
Designed to run after each assistant response so the supervisor dashboard
gets a fresh sentiment reading without slowing down the voice pipeline.

Sentiment labels:
  positive   — customer is happy, thankful, engaged
  neutral    — transactional, calm, no strong signal
  frustrated — mild irritation, repetition, raised tone signals
  angry      — explicit complaints, hostility, threatening to leave
  distressed — urgency, fear, crisis language (e.g. fraud, emergency)

The score (0.0–1.0) represents confidence in the label, not severity.
"""

import asyncio
import json
import os
import re
from typing import Literal

import anthropic
from loguru import logger

SentimentLabel = Literal["positive", "neutral", "frustrated", "angry", "distressed"]

_SENTIMENT_PROMPT = """\
You are a sentiment classifier for a live customer service call transcript.

Read the conversation turns below and return a JSON object with exactly these fields:
  "label": one of "positive", "neutral", "frustrated", "angry", "distressed"
  "score": confidence float 0.0–1.0
  "reason": one short sentence explaining the signal

Rules:
- Base the label on the CUSTOMER turns only (role=user). Ignore agent turns.
- "distressed" means urgency or fear (fraud, emergency, health). Takes priority over angry.
- "frustrated" = mild irritation, asking the same thing twice, sighing language.
- If there are no customer turns yet, return neutral with score 0.5.
- Respond with ONLY the raw JSON object. No markdown fences, no explanation, no extra text.

Transcript (last {n} turns):
{transcript}
"""


async def analyze_sentiment(
    transcript: list[dict],
    window: int = 6,
) -> dict:
    """
    Analyze the last `window` turns of a transcript.

    Args:
        transcript: list of {"role": "user"|"assistant", "text": str}
        window:     how many turns to look at (default 6 = ~3 exchanges)

    Returns:
        {"label": str, "score": float, "reason": str}
    """
    recent = transcript[-window:] if len(transcript) > window else transcript

    if not recent:
        return {"label": "neutral", "score": 0.5, "reason": "No turns yet."}

    turns_text = "\n".join(
        f"{t['role'].upper()}: {t.get('text', '')}"
        for t in recent
        if t.get("text")
    )

    prompt = _SENTIMENT_PROMPT.format(n=len(recent), transcript=turns_text)

    try:
        client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        resp = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=128,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        # Strip markdown code fences if Claude wraps the JSON (e.g. ```json ... ```)
        raw = re.sub(r"^```[a-z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
        if not raw:
            raise ValueError("Empty response from model")
        result = json.loads(raw)
        # Validate shape
        label = result.get("label", "neutral")
        if label not in ("positive", "neutral", "frustrated", "angry", "distressed"):
            label = "neutral"
        return {
            "label": label,
            "score": float(result.get("score", 0.5)),
            "reason": str(result.get("reason", "")),
        }
    except Exception as exc:
        logger.warning(f"[sentiment] analysis failed: {exc}")
        return {"label": "neutral", "score": 0.5, "reason": "Analysis unavailable."}


def needs_supervisor_alert(sentiment: dict) -> bool:
    """True when a supervisor should be notified immediately."""
    label = sentiment.get("label", "neutral")
    score = sentiment.get("score", 0.0)
    if label == "distressed":
        return True
    if label == "angry" and score >= 0.7:
        return True
    return False
