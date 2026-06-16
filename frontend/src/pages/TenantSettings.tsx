import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Save, Loader2, CheckCircle, AlertCircle } from 'lucide-react'
import { api } from '../api'

export default function TenantSettings() {
  const { tenantId } = useParams<{ tenantId: string }>()
  const qc = useQueryClient()

  const { data: tenant, isLoading } = useQuery({
    queryKey: ['tenant', tenantId],
    queryFn: () => api.getTenant(tenantId!),
  })

  const [form, setForm] = useState<any>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (tenant) setForm({ ...tenant })
  }, [tenant])

  const mutation = useMutation({
    mutationFn: (body: any) => api.updateTenant(tenantId!, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tenant', tenantId] })
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    },
  })

  if (isLoading || !form) return <div className="text-slate-500 py-16 text-center">Loading...</div>

  function Field({ label, field, multiline, hint }: { label: string; field: string; multiline?: boolean; hint?: string }) {
    return (
      <div>
        <label className="label">{label}</label>
        {multiline ? (
          <textarea
            rows={3}
            className="input resize-none"
            value={form[field] ?? ''}
            onChange={e => setForm({ ...form, [field]: e.target.value })}
          />
        ) : (
          <input
            className="input"
            value={form[field] ?? ''}
            onChange={e => setForm({ ...form, [field]: e.target.value })}
          />
        )}
        {hint && <p className="text-xs text-slate-500 mt-1">{hint}</p>}
      </div>
    )
  }

  return (
    <div className="max-w-2xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Settings</h1>
          <p className="text-slate-400 text-sm mt-1">{tenant?.name}</p>
        </div>
        <button
          className="btn-primary flex items-center gap-2"
          onClick={() => mutation.mutate(form)}
          disabled={mutation.isPending}
        >
          {mutation.isPending
            ? <><Loader2 size={15} className="animate-spin" /> Saving...</>
            : saved
            ? <><CheckCircle size={15} /> Saved</>
            : <><Save size={15} /> Save changes</>}
        </button>
      </div>

      {mutation.isError && (
        <div className="flex items-center gap-2 text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3 mb-6 text-sm">
          <AlertCircle size={16} /> {(mutation.error as any)?.message}
        </div>
      )}

      <div className="flex flex-col gap-5">
        <div className="card flex flex-col gap-4">
          <p className="text-xs text-slate-500 uppercase tracking-wider font-medium">Business details</p>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Business name" field="name" />
            <Field label="Phone number" field="phone" />
            <Field label="Location" field="location" />
            <Field label="Google Calendar ID" field="google_calendar_id"
              hint="'primary' = main calendar. Find the ID in Google Calendar → Settings." />
          </div>
          <Field label="Business hours" field="hours" />
        </div>

        <div className="card flex flex-col gap-4">
          <p className="text-xs text-slate-500 uppercase tracking-wider font-medium">Services</p>
          <div>
            <label className="label">Services offered (one per line)</label>
            <textarea
              rows={5}
              className="input resize-none"
              value={(form.services || []).join('\n')}
              onChange={e => setForm({ ...form, services: e.target.value.split('\n').filter(Boolean) })}
            />
          </div>
        </div>

        <div className="card flex flex-col gap-4">
          <p className="text-xs text-slate-500 uppercase tracking-wider font-medium">Agent behaviour</p>
          {form.emergency_triage !== undefined && (
            <Field label="Emergency triage rule" field="emergency_triage" multiline
              hint="Defines when and how the agent escalates to an emergency transfer." />
          )}
          <Field label="Human handoff rule" field="human_handoff" multiline
            hint="When the agent should transfer or take a message for a human." />
        </div>
      </div>
    </div>
  )
}
