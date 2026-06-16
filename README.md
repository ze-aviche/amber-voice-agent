# AI Receptionist — Learning Scaffold

A voice AI receptionist built to *learn the conversational-AI stack deeply*,
starting with the dentist vertical. Optimized for understanding, not speed.

The rule that shapes everything: **make ONE phone call excellent before
building any platform around it.** Latency, turn-taking, interruption, and
escalation all live inside that one call. The platform (multi-tenancy, wizard,
dashboard) is comparatively mechanical once the call is solid.

## Stack (and why each piece)

| Stage | Choice | Why |
|---|---|---|
| Orchestration | **Pipecat** (v1.0, Apr 2026) | Explicit pipeline you wire by hand — you *see* every stage. Best for learning. |
| Transport | Local mic → then **Twilio** | Remove telephony as a variable while learning; swap it in later. |
| STT | **Deepgram Nova-3** | Streaming partial transcripts, fast. |
| LLM | **Claude Haiku** | Fast model = the product. Latency beats raw intelligence for routine turns. |
| TTS | **Cartesia Sonic** | Time-to-first-byte leader → reply *starts* almost instantly. |

## Setup

```bash
# uv is Pipecat's recommended runner
uv sync
cp .env.template .env   # then paste your API keys
```

Get keys: Anthropic (console.anthropic.com), Deepgram (deepgram.com),
Cartesia (cartesia.ai). All have free tiers big enough for Phase 1.

## Run (Phase 1, week 1 — local, no phone)

```bash
uv run agent/bot.py
```

Local Commands — Skove AI
1. First-time setup

uv sync
cp .env.template .env   # add ANTHROPIC_API_KEY, DEEPGRAM_API_KEY, CARTESIA_API_KEY
2. Seed the database (run once)

uv run python seed.py
Upserts two tenants into tenants.db: bright-smile-dental and tacos-el-rey. Safe to re-run.

3. Run the voice bot

# Dental tenant (default dev target)
uv run bot.py --tenant bright-smile-dental

# Restaurant tenant
uv run bot.py --tenant tacos-el-rey
4. Run the API server

uv run uvicorn api:app --reload --port 8000
Serves REST endpoints at http://localhost:8000/api/...

5. List audio input devices (troubleshoot mic issues)

uv run python -c "import pyaudio; p = pyaudio.PyAudio(); [print(i, p.get_device_info_by_index(i)['name'], '| in:', p.get_device_info_by_index(i)['maxInputChannels']) for i in range(p.get_device_count())]"
Typical dev session order: seed.py once → bot.py --tenant <id> to test the voice loop → uvicorn api:app to test the REST layer.



Talk to it. It's the front desk at "Bright Smile Dental." Try: booking a
cleaning, asking your hours, and — importantly — *interrupting it mid-sentence*
and saying you have a knocked-out tooth. Watch it stop and escalate.

To know you input devices run below command:

uv run python -c "import pyaudio; p = pyaudio.PyAudio(); [print(i, p.get_device_info_by_index(i)['name'], '| in:', p.get_device_info_by_index(i)['maxInputChannels']) for i in range(p.get_device_count())]"


## The latency budget (your obsession in Phase 1)

Pipecat's own target is a **500–800ms** perceived round trip. The budget:

```
caller stops speaking
  → endpointing delay   ~100-300ms   (VAD deciding the turn ended — TUNABLE)
  → STT final           ~100-200ms
  → LLM first token     ~200-400ms   (why we use Haiku, not a big model)
  → TTS first audio     ~100-150ms   (why we use Cartesia)
  → caller hears reply
```

The single biggest *perceived* lever is **streaming** at every stage: the bot
should start talking as soon as the first tokens/audio exist, never after the
full response is ready. The second is **endpointing** — too eager and it
interrupts the caller; too patient and it feels laggy. This is the dial your
CCaaS ear is best at judging. `enable_metrics=True` is already on; read the
metrics it logs.

## The three things to tune (the soul of the system)

1. **Endpointing** — when has the caller *actually* finished, vs. just paused
   to think? Tune the VAD stop-seconds.
2. **Interruption (barge-in)** — `allow_interruptions=True` is set. Confirm the
   bot stops *instantly* when you talk over it. A bot that keeps talking over
   you feels broken.
3. **Latency** — measure, don't guess.

## Build sequence

- **Phase 1 (wk 1–3): the voice loop.** This scaffold. Local first, then point
  Twilio at the same pipeline. Goal: a call that sounds human.
- **Phase 2 (wk 3–5): make it DO things.** Add tool-calling — check calendar,
  book a slot, take a message, transfer. Add escalation routing (your edge).
  A bot that books is a product; a bot that chats is a demo.
- **Phase 3 (wk 5–7): config as data.** Pull `PRACTICE` out into a per-tenant
  config the engine loads at runtime. Same engine, any dentist. Add the
  restaurant template to pressure-test the schema's flexibility.
- **Phase 4 (wk 7–10): wizard + dashboard.** The 3-minute guided onboarding
  writes to the config store; a dashboard shows call logs/transcripts. *Now*
  it's a self-serve product.

## Two verticals, one engine

Dentist = appointment-centric, high-value, few calls, HIPAA in scope.
Restaurant = high-volume, low-value-per-call, order/reservation accuracy,
noisy-environment robustness, dinner-rush concurrency. Building both forces the
Phase 3 config schema to be genuinely general instead of dentist-shaped.
