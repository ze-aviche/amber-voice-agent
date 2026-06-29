"""
AI Receptionist — Phase 3: multi-tenant voice agent
=====================================================

The pipeline is identical to Phase 1/2. What changed:
  - Tenant config is loaded from SQLite (tenants.db) at startup
  - The system prompt is generated from that config, not hardcoded
  - Tools and persona are routed by vertical (dental | restaurant)
  - Adding a new client = inserting a DB row, no code change

Run:
    uv run bot.py --tenant bright-smile-dental
    uv run bot.py --tenant tacos-el-rey

Seed the DB first if you haven't:
    uv run python seed.py
"""

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone

import anthropic

from dotenv import load_dotenv
from loguru import logger

from pipecat.pipeline.pipeline import Pipeline
from pipecat.workers.runner import WorkerRunner
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.anthropic.llm import AnthropicLLMService
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.frames.frames import LLMContextFrame
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.frames.frames import MetricsFrame, TranscriptionFrame, TextFrame
from pipecat.metrics.metrics import TTFBMetricsData, LLMUsageMetricsData

from db import init_db, get_tenant, insert_call, update_call
from sentiment import analyze_sentiment, needs_supervisor_alert

load_dotenv()


class LatencyObserver(BaseObserver):
    """Collects TTFB and token-usage metrics from MetricsFrames as they flow through the pipeline."""

    def __init__(self):
        super().__init__()
        self.ttfb: dict[str, float] = {}   # processor_name → seconds
        self.tokens: dict[str, LLMUsageMetricsData] = {}

    async def on_push_frame(self, data: FramePushed) -> None:
        if not isinstance(data.frame, MetricsFrame):
            return
        for m in data.frame.data:
            if isinstance(m, TTFBMetricsData):
                self.ttfb[m.processor] = m.value
            elif isinstance(m, LLMUsageMetricsData):
                self.tokens[m.processor] = m

    def report(self) -> None:
        if not self.ttfb and not self.tokens:
            return
        lines = ["── Latency report ──────────────────"]
        for proc, secs in self.ttfb.items():
            lines.append(f"  TTFB  {proc:<30} {secs*1000:6.0f} ms")
        for proc, m in self.tokens.items():
            u = m.value
            lines.append(
                f"  tokens {proc:<29} in={u.prompt_tokens} out={u.completion_tokens}"
            )
        lines.append("────────────────────────────────────")
        logger.info("\n".join(lines))


class SentimentObserver(BaseObserver):
    """
    After each LLM text output, re-scores sentiment from the growing transcript
    and publishes the result to the live call WebSocket feed.

    Uses TranscriptionFrame (user speech→text) and TextFrame (LLM output) to
    build an in-memory transcript, then calls analyze_sentiment() async.
    """

    def __init__(self, app_resources: dict):
        super().__init__()
        self._resources = app_resources
        self._pending: list[dict] = []   # turns collected since last score

    async def on_push_frame(self, data: FramePushed) -> None:
        frame = data.frame

        if isinstance(frame, TranscriptionFrame):
            turn = {"role": "user", "text": frame.text}
            self._resources["transcript"].append(turn)
            self._pending.append(turn)

        elif isinstance(frame, TextFrame) and frame.text.strip():
            turn = {"role": "assistant", "text": frame.text}
            self._resources["transcript"].append(turn)
            self._pending.append(turn)

            # Score after every assistant turn (end of each exchange)
            if len(self._pending) >= 2:
                asyncio.create_task(self._score())
                self._pending = []

    async def _score(self) -> None:
        transcript = self._resources.get("transcript", [])
        sentiment = await analyze_sentiment(transcript, window=8)
        self._resources["sentiment"] = sentiment

        call_id = self._resources.get("call_id", "")
        if needs_supervisor_alert(sentiment):
            logger.warning(
                f"[sentiment] ALERT call={call_id} "
                f"label={sentiment['label']} score={sentiment['score']:.2f} — {sentiment['reason']}"
            )

        # Publish to WebSocket subscribers via api.py shared state
        try:
            from api import publish_call_update
            publish_call_update(call_id, {
                "sentiment": sentiment,
                "outcome": self._resources.get("outcome", "active"),
            })
        except Exception:
            pass   # api may not be running in the same process in local mode


def _load_vertical(vertical: str):
    """Return (build_system_prompt, TOOLS_SCHEMA, TOOL_HANDLERS) for the vertical."""
    if vertical == "dental":
        from dentist_persona import build_system_prompt
        from tools import TOOLS_SCHEMA, TOOL_HANDLERS
        return build_system_prompt, TOOLS_SCHEMA, TOOL_HANDLERS
    elif vertical == "restaurant":
        from restaurant_persona import build_system_prompt
        from restaurant_tools import TOOLS_SCHEMA, TOOL_HANDLERS
        return build_system_prompt, TOOLS_SCHEMA, TOOL_HANDLERS
    elif vertical == "banking":
        from banking_persona import build_system_prompt
        from banking_tools import TOOLS_SCHEMA, TOOL_HANDLERS
        return build_system_prompt, TOOLS_SCHEMA, TOOL_HANDLERS
    else:
        raise ValueError(f"Unknown vertical: {vertical!r}. Must be 'dental', 'restaurant', or 'banking'.")


async def main(tenant_id: str):
    init_db()
    tenant = get_tenant(tenant_id)
    if not tenant:
        logger.error(f"Tenant '{tenant_id}' not found. Run: uv run python seed.py")
        sys.exit(1)

    logger.info(f"Starting agent for: {tenant['name']} (vertical={tenant['vertical']})")

    build_system_prompt, tools_schema, tool_handlers = _load_vertical(tenant["vertical"])

    transport = LocalAudioTransport(
        LocalAudioTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            input_device_index=1,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(
                confidence=0.85,
                min_volume=0.75,
                start_secs=0.3,
                stop_secs=0.4,
            )),
        )
    )

    stt = DeepgramSTTService(
        api_key=os.getenv("DEEPGRAM_API_KEY"),
        model="nova-3",
    )

    llm = AnthropicLLMService(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        model="claude-haiku-4-5-20251001",
    )

    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"),
        voice_id=os.getenv("CARTESIA_VOICE_ID", "a0e99841-438c-4a64-b679-ae501e7d6091"),
    )

    messages = [{"role": "system", "content": build_system_prompt(tenant)}]
    context = LLMContext(messages, tools=tools_schema)
    context_aggregator = LLMContextAggregatorPair(context)

    for name, handler in tool_handlers.items():
        llm.register_function(name, handler)

    # AudioBufferProcessor captures both sides of the call (user mic + bot TTS).
    # We use the on_audio_data event handler to grab audio when stop_recording()
    # fires — whether triggered by EndFrame (clean exit) or CancelFrame (Ctrl+C /
    # caller disconnect). Reading buffers directly in finally is too late: the
    # CancelFrame handler inside the processor resets them before finally runs.
    recorder = AudioBufferProcessor(sample_rate=44100)
    _captured: dict = {"audio": b"", "sample_rate": 44100, "channels": 1}

    @recorder.event_handler("on_audio_data")
    async def _on_audio_data(_, audio: bytes, sample_rate: int, num_channels: int):
        _captured["audio"] = audio
        _captured["sample_rate"] = sample_rate
        _captured["channels"] = num_channels

    pipeline = Pipeline([
        transport.input(),
        stt,
        context_aggregator.user(),
        llm,
        tts,
        recorder,               # captures bot audio after TTS
        transport.output(),
        context_aggregator.assistant(),
    ])

    # Session state — populated during the call, flushed to DB on exit
    call_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    insert_call({
        "id": call_id,
        "tenant_id": tenant_id,
        "started_at": started_at,
        "ended_at": None,
        "duration_secs": None,
        "outcome": "active",       # updated to real outcome on exit
        "caller_number": None,
        "transcript": [],
        "recording_path": None,
        "summary": None,
    })

    app_resources = {
        "tenant": tenant,
        "last_slots": {},
        "call_id": call_id,
        "transcript": [],         # appended by tool handlers / context observer
        "outcome": "info",
        "caller_name": None,      # set by tools when patient name is captured
        "sentiment": {"label": "neutral", "score": 0.5, "reason": "Call just started."},
    }

    latency = LatencyObserver()
    sentiment_obs = SentimentObserver(app_resources)

    task = PipelineWorker(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
        ),
        observers=[latency, sentiment_obs],
        app_resources=app_resources,
    )

    runner = WorkerRunner()
    await runner.add_workers(task)

    @runner.event_handler("on_ready")
    async def on_ready(runner):
        await recorder.start_recording()
        # Register this call in the live-call feed so the dashboard sees it
        try:
            from api import publish_call_update
            publish_call_update(call_id, {
                "outcome": "active",
                "sentiment": app_resources["sentiment"],
            })
            app_resources["_api_publish"] = publish_call_update
        except Exception:
            pass
        messages.append(
            {"role": "system", "content": "Greet the caller warmly in one short sentence."}
        )
        await task.queue_frames([LLMContextFrame(context=context)])

    try:
        await runner.run()
    finally:
        # _captured is populated by the on_audio_data handler, which fires inside
        # stop_recording() before buffers are reset — works for both clean exits
        # (EndFrame) and abrupt ones (CancelFrame from Ctrl+C / caller disconnect).
        ended_at = datetime.now(timezone.utc).isoformat()
        start_dt = datetime.fromisoformat(started_at)
        end_dt = datetime.fromisoformat(ended_at)
        duration = int((end_dt - start_dt).total_seconds())

        recording_path = None
        audio_bytes = _captured["audio"]
        if audio_bytes:
            import wave
            from pathlib import Path
            recordings_dir = Path("recordings")
            recordings_dir.mkdir(exist_ok=True)
            wav_name = f"{call_id}.wav"
            wav_path = recordings_dir / wav_name
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(_captured["channels"])
                wf.setsampwidth(2)   # 16-bit PCM
                wf.setframerate(_captured["sample_rate"])
                wf.writeframes(audio_bytes)
            recording_path = wav_name
            logger.info(f"Recording saved: {wav_path}")

        # Build transcript from context messages (skip system turns)
        transcript = [
            {"role": m["role"], "text": m["content"] if isinstance(m["content"], str) else ""}
            for m in context._messages
            if m["role"] in ("user", "assistant") and isinstance(m.get("content"), str)
        ]

        latency.report()

        summary = None
        if transcript:
            try:
                _ac = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
                transcript_text = "\n".join(
                    f"{t['role'].upper()}: {t['text']}" for t in transcript if t.get("text")
                )
                outcome_label = app_resources.get("outcome", "info")
                _resp = await _ac.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=128,
                    messages=[{
                        "role": "user",
                        "content": (
                            f"Summarize this dental receptionist call in one sentence. "
                            f"Outcome: {outcome_label}.\n\nTranscript:\n{transcript_text}"
                        ),
                    }],
                )
                summary = _resp.content[0].text.strip()
                logger.info(f"Call summary: {summary}")
            except Exception as exc:
                logger.warning(f"Summary generation failed: {exc}")

        update_call(
            call_id,
            ended_at=ended_at,
            duration_secs=duration,
            outcome=app_resources.get("outcome", "info"),
            caller_number=app_resources.get("caller_name"),
            transcript=transcript,
            recording_path=recording_path,
            summary=summary,
        )
        logger.info(f"Call {call_id} logged: {duration}s, outcome={app_resources.get('outcome')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Receptionist")
    parser.add_argument(
        "--tenant",
        default="bright-smile-dental",
        help="Tenant ID from the database (default: bright-smile-dental)",
    )
    args = parser.parse_args()

    import asyncio
    asyncio.run(main(args.tenant))
