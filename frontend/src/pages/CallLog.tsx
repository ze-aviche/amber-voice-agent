import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Phone, ChevronDown, ChevronRight, PlayCircle, Clock, Calendar } from 'lucide-react'
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

function fmtDate(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  })
}

function CallRow({ call, tenantId }: { call: any; tenantId: string }) {
  const [open, setOpen] = useState(false)

  return (
    <>
      <tr
        className="border-b border-slate-700/50 hover:bg-slate-700/20 cursor-pointer transition-colors"
        onClick={() => setOpen(o => !o)}
      >
        <td className="py-3 px-4">
          <div className="flex items-center gap-2 text-slate-300 text-sm">
            <Phone size={13} className="text-slate-500" />
            {call.caller_number || 'Unknown'}
          </div>
        </td>
        <td className="py-3 px-4 text-sm text-slate-400">
          <div className="flex items-center gap-1.5">
            <Calendar size={12} />
            {fmtDate(call.started_at)}
          </div>
        </td>
        <td className="py-3 px-4 text-sm text-slate-400">
          <div className="flex items-center gap-1.5">
            <Clock size={12} />
            {fmt(call.duration_secs)}
          </div>
        </td>
        <td className="py-3 px-4">
          <span className={`badge ${OUTCOME_STYLE[call.outcome] ?? 'badge-info'} capitalize`}>
            {call.outcome || 'unknown'}
          </span>
        </td>
        <td className="py-3 px-4 text-sm text-slate-400 max-w-xs truncate">{call.summary || '—'}</td>
        <td className="py-3 px-4">
          <div className="flex items-center gap-2 justify-end">
            {call.recording_path && (
              <Link
                to={`/${tenantId}/calls/${call.id}`}
                onClick={e => e.stopPropagation()}
                className="text-indigo-400 hover:text-indigo-300 transition-colors"
              >
                <PlayCircle size={16} />
              </Link>
            )}
            {open ? <ChevronDown size={14} className="text-slate-500" /> : <ChevronRight size={14} className="text-slate-500" />}
          </div>
        </td>
      </tr>

      {open && call.transcript?.length > 0 && (
        <tr className="border-b border-slate-700/30 bg-slate-900/40">
          <td colSpan={6} className="px-6 py-4">
            <div className="flex flex-col gap-2 max-h-64 overflow-y-auto">
              {call.transcript.map((t: any, i: number) => (
                <div key={i} className={`flex gap-3 text-sm ${t.role === 'assistant' ? 'justify-start' : 'justify-end'}`}>
                  <div className={`px-3 py-2 rounded-xl max-w-md leading-relaxed
                    ${t.role === 'assistant'
                      ? 'bg-slate-700 text-slate-200 rounded-tl-sm'
                      : 'bg-indigo-500/20 text-indigo-200 rounded-tr-sm'}`}>
                    {t.text}
                  </div>
                </div>
              ))}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

export default function CallLog() {
  const { tenantId } = useParams<{ tenantId: string }>()
  const { data: calls, isLoading } = useQuery({
    queryKey: ['calls', tenantId],
    queryFn: () => api.listCalls(tenantId!),
    refetchInterval: 15_000,
  })
  const { data: tenant } = useQuery({
    queryKey: ['tenant', tenantId],
    queryFn: () => api.getTenant(tenantId!),
  })

  const stats = calls ? {
    total: calls.length,
    booked: calls.filter(c => c.outcome === 'booked').length,
    messages: calls.filter(c => c.outcome === 'message').length,
    avgDur: calls.filter(c => c.duration_secs).reduce((s, c) => s + c.duration_secs, 0) / (calls.filter(c => c.duration_secs).length || 1),
  } : null

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-100">{tenant?.name ?? 'Call Log'}</h1>
        <p className="text-slate-400 text-sm mt-1 capitalize">{tenant?.vertical} · {tenant?.location}</p>
      </div>

      {stats && (
        <div className="grid grid-cols-4 gap-4 mb-6">
          {[
            { label: 'Total calls', value: stats.total },
            { label: 'Appointments booked', value: stats.booked },
            { label: 'Messages taken', value: stats.messages },
            { label: 'Avg duration', value: fmt(Math.round(stats.avgDur)) },
          ].map(s => (
            <div key={s.label} className="card py-4">
              <p className="text-2xl font-semibold text-slate-100">{s.value}</p>
              <p className="text-xs text-slate-400 mt-1">{s.label}</p>
            </div>
          ))}
        </div>
      )}

      <div className="card p-0 overflow-hidden">
        {isLoading ? (
          <div className="py-16 text-center text-slate-500">Loading calls...</div>
        ) : !calls?.length ? (
          <div className="py-16 text-center">
            <Phone size={28} className="text-slate-600 mx-auto mb-3" />
            <p className="text-slate-400">No calls yet.</p>
            <p className="text-slate-500 text-sm mt-1">Calls will appear here once the bot answers its first call.</p>
          </div>
        ) : (
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-slate-700 text-xs text-slate-500 uppercase tracking-wider">
                {['Caller', 'Date', 'Duration', 'Outcome', 'Summary', ''].map(h => (
                  <th key={h} className="px-4 py-3 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {calls.map(c => <CallRow key={c.id} call={c} tenantId={tenantId!} />)}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
