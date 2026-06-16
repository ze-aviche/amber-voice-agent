# Skove AI — AI Receptionist Platform

## What This Is
An autonomous AI receptionist platform for SMBs. Any business deploys in 3 minutes, no code required. Starting with two verticals: **dental practices** and **restaurants**.

The owner is a CCaaS expert (Amazon Connect, Genesys) using this project partly to learn the modern conversational-AI stack. Optimize for correctness and learning, not just shipping.

## Current Phase: Phase 1 — The Voice Loop
One hardcoded dentist agent. Local mic first, then Twilio. Goal: one phone call that sounds human.

**Do not add platform features (multi-tenancy, dashboard, wizard) until the voice loop is excellent.**

## File Map
- [bot.py](bot.py) — Pipecat pipeline: transport → STT → LLM → TTS. The entire voice loop.
- [dentist_persona.py](dentist_persona.py) — Hardcoded dentist config (seed of future per-tenant schema). Keep persona data separate from pipeline logic.

## Stack
| Stage | Choice |
|---|---|
| Orchestration | Pipecat v1.0 |
| Transport | LocalAudioTransport (Phase 1) → Twilio Media Streams (Phase 1 week 2) |
| STT | Deepgram Nova-3 streaming |
| LLM | Claude Haiku (`claude-haiku-4-5-20251001`) |
| TTS | Cartesia Sonic (default); Miso TTS 8B (future A/B experiment) |

## Architecture Rules
- **Swap the transport, keep the pipeline.** The pipeline (STT→LLM→TTS) never changes when you go from local mic to Twilio to SIP.
- **Persona is data, not code.** `PRACTICE` dict in `dentist_persona.py` is the seed of the Phase 3 per-tenant config schema. Never hardcode business details inside `bot.py`.
- **TTS is swappable.** One import swap to change TTS provider. Keep `CartesiaTTSService` as the Phase 1 default.
- **HIPAA from day one.** Dental vertical touches patient data — design for BAA-ready architecture. Never log PII to plaintext.

## The Three Things That Make It Feel Human
1. **Endpointing** — when has the caller actually finished (vs. just paused)? Tune VAD stop-seconds.
2. **Interruption (barge-in)** — `allow_interruptions=True` is set. Bot must stop *instantly* when caller talks over it.
3. **Latency budget** — target <800ms perceived round trip: endpointing (~300ms) + STT (~150ms) + LLM first token (~300ms) + TTS first audio (~150ms). Stream at every stage; never wait for a complete response.

## Build Phases
- **Phase 1 (wk 1–3)**: Single hardcoded dentist, local mic → Twilio. Learn pipeline internals.
- **Phase 2 (wk 3–5)**: Tool-calling — calendar check, booking, message-taking, transfer. Escalation routing.
- **Phase 3 (wk 5–7)**: Config as data — pull `PRACTICE` into per-tenant JSON schema loaded at runtime.
- **Phase 4 (wk 7–10)**: Onboarding wizard + call log dashboard. Wizard writes to Phase 3 config store.

## Run
```bash
uv sync
cp .env.template .env   # add ANTHROPIC_API_KEY, DEEPGRAM_API_KEY, CARTESIA_API_KEY
uv run bot.py
```

Test escalation: interrupt mid-sentence with "I knocked out my tooth" — bot must stop and escalate, not book a cleaning.

## Vertical Notes
- **Dental**: appointment booking/rescheduling, new-patient intake, insurance Q&A, emergency triage. Integrations: Dentrix, Open Dental, NexHealth. HIPAA scope.
- **Restaurant**: reservations, takeout/order capture, hours/wait-time, high-concurrency dinner rush. Integrations: OpenTable, Resy, Toast.

Build dental fully first. Then prove restaurant template slots into the same engine to validate the Phase 3 config schema is genuinely general.
