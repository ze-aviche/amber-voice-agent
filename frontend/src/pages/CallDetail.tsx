import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Phone, Clock, Calendar, Download } from 'lucide-react'
import { api } from '../api'

const OUTCOME_STYLE: Record<string, string> = {
  booked:    'badge-booked',
  message:   'badge-message',
  transfer:  'badge-transfer',
  info:      'badge-info',
  abandoned: 'badge-abandoned',
}

function fmt(secs: number | null) {
  if (!secs) return '—'
  const m = Math.floor(secs / 60), s = secs % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

export default function CallDetail() {
  const { tenantId, callId } = useParams<{ tenantId: string; callId: string }>()
  const { data: call, isLoading } = useQuery({
    queryKey: ['call', callId],
    queryFn: () => api.getCall(callId!),
  })

  if (isLoading) return <div className="text-slate-500 py-16 text-center">Loading...</div>
  if (!call) return <div className="text-slate-500 py-16 text-center">Call not found.</div>

  const recordingUrl = call.recording_path ? api.recordingUrl(callId!) : null

  return (
    <div className="max-w-3xl">
      <Link to={`/${tenantId}/calls`} className="flex items-center gap-2 text-slate-400 hover:text-slate-100 transition-colors text-sm mb-6">
        <ArrowLeft size={14} /> Back to call log
      </Link>

      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100 flex items-center gap-2">
            <Phone size={18} className="text-slate-400" />
            {call.caller_number || 'Unknown caller'}
          </h1>
          <div className="flex items-center gap-4 mt-2 text-sm text-slate-400">
            <span className="flex items-center gap-1.5"><Calendar size={12} />
              {new Date(call.started_at).toLocaleString()}
            </span>
            <span className="flex items-center gap-1.5"><Clock size={12} /> {fmt(call.duration_secs)}</span>
            <span className={`badge ${OUTCOME_STYLE[call.outcome] ?? 'badge-info'} capitalize`}>
              {call.outcome || 'unknown'}
            </span>
          </div>
        </div>
      </div>

      {call.summary && (
        <div className="card mb-6">
          <p className="text-xs text-slate-500 uppercase tracking-wider mb-2">Summary</p>
          <p className="text-slate-200">{call.summary}</p>
        </div>
      )}

      {recordingUrl && (
        <div className="card mb-6">
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs text-slate-500 uppercase tracking-wider">Recording</p>
            <a href={recordingUrl} download className="flex items-center gap-1 text-xs text-indigo-400 hover:text-indigo-300 transition-colors">
              <Download size={12} /> Download
            </a>
          </div>
          <audio
            controls
            src={recordingUrl}
            className="w-full"
            style={{ colorScheme: 'dark' }}
          />
        </div>
      )}

      <div className="card">
        <p className="text-xs text-slate-500 uppercase tracking-wider mb-4">Transcript</p>
        {!call.transcript?.length ? (
          <p className="text-slate-500 text-sm">No transcript available.</p>
        ) : (
          <div className="flex flex-col gap-3">
            {call.transcript.map((t: any, i: number) => (
              <div key={i} className={`flex gap-3 ${t.role === 'assistant' ? '' : 'flex-row-reverse'}`}>
                <div className={`w-7 h-7 rounded-full shrink-0 flex items-center justify-center text-xs font-semibold
                  ${t.role === 'assistant' ? 'bg-indigo-500/20 text-indigo-400' : 'bg-slate-700 text-slate-400'}`}>
                  {t.role === 'assistant' ? 'AI' : 'C'}
                </div>
                <div className={`px-4 py-2.5 rounded-2xl max-w-lg text-sm leading-relaxed
                  ${t.role === 'assistant'
                    ? 'bg-slate-700 text-slate-200 rounded-tl-sm'
                    : 'bg-indigo-500/15 text-indigo-100 rounded-tr-sm'}`}>
                  {t.text}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
