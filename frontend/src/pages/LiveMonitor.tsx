/**
 * LiveMonitor — Supervisor Dashboard
 *
 * Shows all active calls with live transcript and sentiment indicators.
 * Connects to /ws/calls/{call_id} via WebSocket for each active call.
 * Falls back to polling /api/live-calls if WebSocket is unavailable.
 */

import { useEffect, useRef, useState } from 'react'
import { Activity, AlertTriangle, CheckCircle, Minus, TrendingDown, TrendingUp } from 'lucide-react'

const WS_BASE = 'ws://localhost:8000'
const API_BASE = 'http://localhost:8000'

type SentimentLabel = 'positive' | 'neutral' | 'frustrated' | 'angry' | 'distressed'

interface Sentiment {
  label: SentimentLabel
  score: number
  reason: string
}

interface Turn {
  role: 'user' | 'assistant'
  text: string
}

interface LiveCall {
  call_id: string
  transcript: Turn[]
  sentiment: Sentiment | null
  outcome: string
}

// ── Sentiment config ──────────────────────────────────────────────────────────

const SENTIMENT_CONFIG: Record<SentimentLabel, {
  color: string
  bg: string
  ring: string
  Icon: React.ElementType
  label: string
}> = {
  positive:   { color: 'text-emerald-400', bg: 'bg-emerald-500/10', ring: 'ring-emerald-500/40', Icon: TrendingUp,     label: 'Positive' },
  neutral:    { color: 'text-slate-400',   bg: 'bg-slate-700/30',   ring: 'ring-slate-600/40',   Icon: Minus,          label: 'Neutral' },
  frustrated: { color: 'text-amber-400',   bg: 'bg-amber-500/10',   ring: 'ring-amber-500/40',   Icon: TrendingDown,   label: 'Frustrated' },
  angry:      { color: 'text-red-400',     bg: 'bg-red-500/10',     ring: 'ring-red-500/40',     Icon: AlertTriangle,  label: 'Angry' },
  distressed: { color: 'text-red-300',     bg: 'bg-red-600/20',     ring: 'ring-red-400/60',     Icon: AlertTriangle,  label: 'Distressed' },
}

function SentimentBadge({ sentiment }: { sentiment: Sentiment | null }) {
  const label = (sentiment?.label ?? 'neutral') as SentimentLabel
  const cfg = SENTIMENT_CONFIG[label] ?? SENTIMENT_CONFIG.neutral
  const { Icon } = cfg
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ring-1 ${cfg.bg} ${cfg.color} ${cfg.ring}`}>
      <Icon size={11} />
      {cfg.label}
      {sentiment && (
        <span className="opacity-60 ml-0.5">{Math.round(sentiment.score * 100)}%</span>
      )}
    </span>
  )
}

function SentimentBar({ sentiment }: { sentiment: Sentiment | null }) {
  const label = (sentiment?.label ?? 'neutral') as SentimentLabel
  const score = sentiment?.score ?? 0.5

  const barColors: Record<SentimentLabel, string> = {
    positive: 'bg-emerald-500',
    neutral:  'bg-slate-500',
    frustrated: 'bg-amber-500',
    angry:    'bg-red-500',
    distressed: 'bg-red-400',
  }

  return (
    <div className="w-full bg-slate-700/50 rounded-full h-1.5 overflow-hidden">
      <div
        className={`h-full rounded-full transition-all duration-700 ${barColors[label]}`}
        style={{ width: `${score * 100}%` }}
      />
    </div>
  )
}

// ── Call card ─────────────────────────────────────────────────────────────────

function CallCard({ call }: { call: LiveCall }) {
  const transcriptRef = useRef<HTMLDivElement>(null)
  const isAlert = call.sentiment?.label === 'distressed' ||
    (call.sentiment?.label === 'angry' && (call.sentiment?.score ?? 0) >= 0.7)

  // Auto-scroll transcript to bottom
  useEffect(() => {
    if (transcriptRef.current) {
      transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight
    }
  }, [call.transcript])

  return (
    <div className={`card flex flex-col gap-4 ring-1 transition-all duration-500
      ${isAlert ? 'ring-red-500/60 shadow-red-900/30 shadow-lg' : 'ring-slate-700/0'}`}>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="relative flex h-2.5 w-2.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500" />
          </div>
          <span className="text-xs font-mono text-slate-400">{call.call_id.slice(0, 8)}…</span>
        </div>
        <div className="flex items-center gap-2">
          <SentimentBadge sentiment={call.sentiment} />
          {isAlert && (
            <span className="inline-flex items-center gap-1 text-xs font-semibold text-red-400 animate-pulse">
              <AlertTriangle size={12} /> Supervisor Alert
            </span>
          )}
        </div>
      </div>

      {/* Sentiment bar */}
      <SentimentBar sentiment={call.sentiment} />

      {/* Sentiment reason */}
      {call.sentiment?.reason && (
        <p className="text-xs text-slate-500 -mt-2 italic">{call.sentiment.reason}</p>
      )}

      {/* Live transcript */}
      <div
        ref={transcriptRef}
        className="flex flex-col gap-2 max-h-64 overflow-y-auto pr-1"
      >
        {call.transcript.length === 0 ? (
          <p className="text-slate-600 text-xs text-center py-4">Waiting for first turn…</p>
        ) : (
          call.transcript.map((t, i) => (
            <div
              key={i}
              className={`flex text-sm ${t.role === 'assistant' ? 'justify-start' : 'justify-end'}`}
            >
              <div className={`px-3 py-2 rounded-xl max-w-xs leading-relaxed text-xs
                ${t.role === 'assistant'
                  ? 'bg-slate-700 text-slate-200 rounded-tl-sm'
                  : 'bg-indigo-500/20 text-indigo-200 rounded-tr-sm'}`}>
                {t.text}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

// ── WebSocket hook ────────────────────────────────────────────────────────────

function useCallFeed(callId: string): LiveCall {
  const [state, setState] = useState<LiveCall>({
    call_id: callId,
    transcript: [],
    sentiment: null,
    outcome: 'active',
  })

  useEffect(() => {
    const ws = new WebSocket(`${WS_BASE}/ws/calls/${callId}`)
    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        if (data.ping) return
        setState(data)
      } catch {}
    }
    return () => ws.close()
  }, [callId])

  return state
}

// ── Per-call live view ────────────────────────────────────────────────────────

function LiveCallView({ callId }: { callId: string }) {
  const call = useCallFeed(callId)
  return <CallCard call={call} />
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function LiveMonitor() {
  const [activeCallIds, setActiveCallIds] = useState<string[]>([])
  const [lastPoll, setLastPoll] = useState<Date | null>(null)

  // Poll /api/live-calls every 5 s to pick up new calls
  useEffect(() => {
    const poll = async () => {
      try {
        const r = await fetch(`${API_BASE}/api/live-calls`)
        const calls: LiveCall[] = await r.json()
        setActiveCallIds(calls.map(c => c.call_id))
        setLastPoll(new Date())
      } catch {}
    }
    poll()
    const id = setInterval(poll, 5_000)
    return () => clearInterval(id)
  }, [])

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100 flex items-center gap-2">
            <Activity size={22} className="text-indigo-400" />
            Live Monitor
          </h1>
          <p className="text-slate-400 text-sm mt-1">Real-time call sentiment and transcript</p>
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-500">
          {lastPoll && (
            <>
              <CheckCircle size={12} className="text-emerald-500" />
              Updated {lastPoll.toLocaleTimeString()}
            </>
          )}
        </div>
      </div>

      {activeCallIds.length === 0 ? (
        <div className="card py-20 text-center">
          <Activity size={32} className="text-slate-600 mx-auto mb-3" />
          <p className="text-slate-400">No active calls right now.</p>
          <p className="text-slate-500 text-sm mt-1">
            Start a call with <code className="text-slate-400">uv run bot.py --tenant first-national-bank</code>
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          {activeCallIds.map(id => (
            <LiveCallView key={id} callId={id} />
          ))}
        </div>
      )}
    </div>
  )
}
