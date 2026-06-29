/**
 * LoanDashboard — Underwriter Review Console
 *
 * Shows all loan applications with their LangGraph state.
 * The key demo: applications stuck at "underwriter_review" show
 * the full credit file and Approve / Decline buttons that resume the graph.
 */

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Landmark, CheckCircle2, XCircle, Clock, AlertTriangle,
  ChevronDown, ChevronRight, TrendingUp, Shield, Building2, FileText,
} from 'lucide-react'

const BASE = 'http://localhost:8000'

// ── Types ─────────────────────────────────────────────────────────────────────

interface LoanApp {
  application_id: string
  customer_name: string
  business_name: string
  requested_amount: number
  current_node: string
  underwriting_decision: string | null
  underwriter_decision: string | null
  is_interrupted: boolean
  offer_generated_at: string | null
  adverse_action_sent: boolean
  kyc_status: string
  credit_score: number | null
  fraud_score: number | null
  annual_revenue: number | null
  // full state fields (from GET /api/loans/{id})
  interest_rate?: number
  term_months?: number
  monthly_payment?: number
  approved_amount?: number
  credit_report_summary?: string
  fraud_flags?: string[]
  business_verified?: boolean
  business_state?: string
  auto_decision_rationale?: string
  decline_reasons?: string[]
  underwriter_id?: string
  underwriter_notes?: string
  ecoa_disclosed_at?: string
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt$(n: number | null | undefined) {
  if (n == null) return '—'
  return `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function nodeLabel(node: string | null, decision: string | null, interrupted: boolean): {
  label: string; color: string; Icon: React.ElementType
} {
  if (interrupted) return { label: 'Awaiting Underwriter', color: 'text-amber-400', Icon: Clock }
  if (node === 'offer_generation' || decision === 'approved')
    return { label: 'Approved', color: 'text-emerald-400', Icon: CheckCircle2 }
  if (node === 'adverse_action_notice' || decision === 'declined')
    return { label: 'Declined', color: 'text-red-400', Icon: XCircle }
  if (node === 'parallel_checks')
    return { label: 'Running Checks', color: 'text-indigo-400', Icon: Clock }
  if (node === 'kyc_verification')
    return { label: 'KYC Verification', color: 'text-slate-400', Icon: Clock }
  return { label: node ?? 'Processing', color: 'text-slate-400', Icon: Clock }
}

function ScoreBar({ value, max = 850, low = 580, high = 720 }: {
  value: number | null; max?: number; low?: number; high?: number
}) {
  if (value == null) return <span className="text-slate-500 text-xs">—</span>
  const pct = (value / max) * 100
  const color = value >= high ? 'bg-emerald-500' : value >= low ? 'bg-amber-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2">
      <span className="text-sm font-medium text-slate-200 w-10">{value}</span>
      <div className="flex-1 bg-slate-700/50 rounded-full h-1.5">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

// ── New Application Form ───────────────────────────────────────────────────────

function NewApplicationForm({ onSubmit }: { onSubmit: (data: any) => void }) {
  const [form, setForm] = useState({
    customer_id: 'CUST-001',
    customer_name: 'James Carter',
    business_name: 'Carter Logistics LLC',
    business_ein: '75-1234567',
    requested_amount: '250000',
    loan_purpose: 'Equipment purchase and working capital',
  })
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm(f => ({ ...f, [k]: e.target.value }))

  return (
    <div className="card mb-6">
      <h2 className="text-sm font-semibold text-slate-300 mb-4">Submit New Application</h2>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label">Customer</label>
          <select className="input" value={form.customer_id} onChange={set('customer_id')}
            onBlur={e => {
              if (e.target.value === 'CUST-001')
                setForm(f => ({ ...f, customer_name: 'James Carter', business_name: 'Carter Logistics LLC', business_ein: '75-1234567' }))
              else
                setForm(f => ({ ...f, customer_name: 'Maria Chen', business_name: 'Chen Consulting Inc', business_ein: '12-9876543' }))
            }}>
            <option value="CUST-001">James Carter (score ~780, strong)</option>
            <option value="CUST-002">Maria Chen (score ~610, borderline)</option>
          </select>
        </div>
        <div>
          <label className="label">Business Name</label>
          <input className="input" value={form.business_name} onChange={set('business_name')} />
        </div>
        <div>
          <label className="label">EIN</label>
          <input className="input" value={form.business_ein} onChange={set('business_ein')} />
        </div>
        <div>
          <label className="label">Loan Amount</label>
          <input className="input" type="number" value={form.requested_amount} onChange={set('requested_amount')} />
        </div>
        <div className="col-span-2">
          <label className="label">Loan Purpose</label>
          <input className="input" value={form.loan_purpose} onChange={set('loan_purpose')} />
        </div>
      </div>
      <button
        className="btn-primary mt-4"
        onClick={() => onSubmit({ ...form, requested_amount: parseFloat(form.requested_amount) })}
      >
        Submit Application
      </button>
    </div>
  )
}

// ── Application Card ──────────────────────────────────────────────────────────

function ApplicationCard({ app, onDecision }: {
  app: LoanApp
  onDecision: (id: string, decision: 'approved' | 'declined') => void
}) {
  const [expanded, setExpanded] = useState(app.is_interrupted)
  const [uwId, setUwId] = useState('UW-JOHNSON')
  const [uwNotes, setUwNotes] = useState('')

  const { label, color, Icon } = nodeLabel(app.current_node, app.underwriting_decision, app.is_interrupted)

  return (
    <div className={`card ring-1 transition-all duration-300
      ${app.is_interrupted ? 'ring-amber-500/50 shadow-amber-900/20 shadow-lg' : 'ring-slate-700/0'}`}>

      {/* Header row */}
      <div
        className="flex items-center justify-between cursor-pointer"
        onClick={() => setExpanded(e => !e)}
      >
        <div className="flex items-center gap-3">
          <div className={`flex items-center gap-1.5 text-xs font-medium ${color}`}>
            <Icon size={14} />
            {label}
          </div>
          <div>
            <p className="font-medium text-slate-100 text-sm">{app.business_name}</p>
            <p className="text-xs text-slate-400">{app.customer_name} · {app.application_id}</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right">
            <p className="text-sm font-semibold text-slate-100">{fmt$(app.requested_amount)}</p>
            <p className="text-xs text-slate-500">requested</p>
          </div>
          {expanded ? <ChevronDown size={14} className="text-slate-500" /> : <ChevronRight size={14} className="text-slate-500" />}
        </div>
      </div>

      {/* Expanded credit file */}
      {expanded && (
        <div className="mt-4 pt-4 border-t border-slate-700/50 flex flex-col gap-4">

          {/* Parallel check results grid */}
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-slate-800/60 rounded-lg p-3">
              <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-2">
                <TrendingUp size={11} /> Credit Score
              </div>
              <ScoreBar value={app.credit_score} />
              {app.credit_report_summary && (
                <p className="text-xs text-slate-500 mt-1 italic">{app.credit_report_summary}</p>
              )}
            </div>

            <div className="bg-slate-800/60 rounded-lg p-3">
              <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-2">
                <Shield size={11} /> Fraud Score
              </div>
              {app.fraud_score != null ? (
                <>
                  <ScoreBar value={Math.round(app.fraud_score * 100)} max={100} low={25} high={15} />
                  {(app.fraud_flags ?? []).length > 0 && (
                    <p className="text-xs text-amber-400 mt-1">{app.fraud_flags!.join(', ')}</p>
                  )}
                </>
              ) : <span className="text-slate-500 text-xs">Pending</span>}
            </div>

            <div className="bg-slate-800/60 rounded-lg p-3">
              <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-2">
                <Building2 size={11} /> Business Verification
              </div>
              {app.business_verified != null ? (
                <span className={`text-sm font-medium ${app.business_verified ? 'text-emerald-400' : 'text-red-400'}`}>
                  {app.business_verified ? `Verified · ${app.business_state}` : 'Not Verified'}
                </span>
              ) : <span className="text-slate-500 text-xs">Pending</span>}
            </div>

            <div className="bg-slate-800/60 rounded-lg p-3">
              <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-2">
                <FileText size={11} /> Annual Revenue (IRS)
              </div>
              <span className="text-sm font-medium text-slate-200">{fmt$(app.annual_revenue)}</span>
            </div>
          </div>

          {/* Auto-decision rationale */}
          {app.auto_decision_rationale && (
            <div className="bg-slate-800/40 rounded-lg px-3 py-2">
              <p className="text-xs text-slate-500 font-medium mb-0.5">Auto-underwriting rationale</p>
              <p className="text-xs text-slate-300">{app.auto_decision_rationale}</p>
            </div>
          )}

          {/* Decline reasons */}
          {(app.decline_reasons ?? []).length > 0 && (
            <div className="bg-red-950/30 rounded-lg px-3 py-2 ring-1 ring-red-500/20">
              <p className="text-xs text-red-400 font-medium mb-1">Decline reasons</p>
              {app.decline_reasons!.map((r, i) => (
                <p key={i} className="text-xs text-red-300">· {r}</p>
              ))}
            </div>
          )}

          {/* Approved offer */}
          {app.offer_generated_at && (
            <div className="bg-emerald-950/30 rounded-lg px-3 py-2 ring-1 ring-emerald-500/20 grid grid-cols-3 gap-2">
              <div><p className="text-xs text-slate-500">Amount</p><p className="text-sm font-semibold text-emerald-300">{fmt$(app.approved_amount)}</p></div>
              <div><p className="text-xs text-slate-500">Rate (APR)</p><p className="text-sm font-semibold text-emerald-300">{app.interest_rate}%</p></div>
              <div><p className="text-xs text-slate-500">Monthly</p><p className="text-sm font-semibold text-emerald-300">{fmt$(app.monthly_payment)}</p></div>
            </div>
          )}

          {/* Human gate — underwriter action panel */}
          {app.is_interrupted && (
            <div className="bg-amber-950/20 rounded-lg p-3 ring-1 ring-amber-500/30">
              <div className="flex items-center gap-2 mb-3">
                <AlertTriangle size={14} className="text-amber-400" />
                <p className="text-xs font-semibold text-amber-300">
                  Graph paused — awaiting underwriter decision
                </p>
              </div>
              <div className="flex flex-col gap-2 mb-3">
                <input
                  className="input text-xs"
                  placeholder="Underwriter ID"
                  value={uwId}
                  onChange={e => setUwId(e.target.value)}
                />
                <input
                  className="input text-xs"
                  placeholder="Notes (optional)"
                  value={uwNotes}
                  onChange={e => setUwNotes(e.target.value)}
                />
              </div>
              <div className="flex gap-2">
                <button
                  className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold py-2 px-3 rounded-lg transition-colors flex items-center justify-center gap-1.5"
                  onClick={() => onDecision(app.application_id, 'approved')}
                >
                  <CheckCircle2 size={13} /> Approve
                </button>
                <button
                  className="flex-1 bg-red-700 hover:bg-red-600 text-white text-xs font-semibold py-2 px-3 rounded-lg transition-colors flex items-center justify-center gap-1.5"
                  onClick={() => onDecision(app.application_id, 'declined')}
                >
                  <XCircle size={13} /> Decline
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function LoanDashboard() {
  const qc = useQueryClient()

  const { data: apps = [], isLoading } = useQuery<LoanApp[]>({
    queryKey: ['loans'],
    queryFn: () => fetch(`${BASE}/api/loans`).then(r => r.json()),
    refetchInterval: 3_000,
  })

  const submitMutation = useMutation({
    mutationFn: (body: any) =>
      fetch(`${BASE}/api/loans`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }).then(r => r.json()),
    onSuccess: () => setTimeout(() => qc.invalidateQueries({ queryKey: ['loans'] }), 500),
  })

  const decisionMutation = useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: string }) =>
      fetch(`${BASE}/api/loans/${id}/decision`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision, underwriter_id: 'UW-JOHNSON', notes: '' }),
      }).then(r => r.json()),
    onSuccess: () => setTimeout(() => qc.invalidateQueries({ queryKey: ['loans'] }), 1_000),
  })

  const pending = apps.filter(a => a.is_interrupted)
  const approved = apps.filter(a => a.offer_generated_at)
  const declined = apps.filter(a => a.adverse_action_sent)
  const processing = apps.filter(a => !a.is_interrupted && !a.offer_generated_at && !a.adverse_action_sent)

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-100 flex items-center gap-2">
          <Landmark size={22} className="text-indigo-400" />
          Loan Processing
        </h1>
        <p className="text-slate-400 text-sm mt-1">
          LangGraph multi-step workflow · human-in-the-loop underwriting
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        {[
          { label: 'Pending Review', value: pending.length, color: 'text-amber-400' },
          { label: 'Processing', value: processing.length, color: 'text-indigo-400' },
          { label: 'Approved', value: approved.length, color: 'text-emerald-400' },
          { label: 'Declined', value: declined.length, color: 'text-red-400' },
        ].map(s => (
          <div key={s.label} className="card py-4">
            <p className={`text-2xl font-semibold ${s.color}`}>{s.value}</p>
            <p className="text-xs text-slate-400 mt-1">{s.label}</p>
          </div>
        ))}
      </div>

      <NewApplicationForm onSubmit={data => submitMutation.mutate(data)} />

      {isLoading ? (
        <div className="py-16 text-center text-slate-500">Loading applications...</div>
      ) : apps.length === 0 ? (
        <div className="card py-16 text-center">
          <Landmark size={28} className="text-slate-600 mx-auto mb-3" />
          <p className="text-slate-400">No applications yet. Submit one above.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {/* Pending review first */}
          {[...apps].sort((a, b) => (b.is_interrupted ? 1 : 0) - (a.is_interrupted ? 1 : 0))
            .map(app => (
              <ApplicationCard
                key={app.application_id}
                app={app}
                onDecision={(id, decision) => decisionMutation.mutate({ id, decision })}
              />
            ))}
        </div>
      )}
    </div>
  )
}
