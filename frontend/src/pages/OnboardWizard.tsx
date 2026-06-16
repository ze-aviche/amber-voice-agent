import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Globe, CheckCircle, ChevronRight, Loader2, AlertCircle } from 'lucide-react'
import { api } from '../api'

type Step = 1 | 2 | 3

function StepIndicator({ current }: { current: Step }) {
  const steps = ['Business URL', 'Review & Edit', 'Deploy']
  return (
    <div className="flex items-center gap-2 mb-8">
      {steps.map((label, i) => {
        const n = (i + 1) as Step
        const done = current > n
        const active = current === n
        return (
          <div key={n} className="flex items-center gap-2">
            <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold transition-colors
              ${done ? 'bg-indigo-500 text-white' : active ? 'bg-indigo-500/20 text-indigo-400 border border-indigo-500' : 'bg-slate-700 text-slate-500'}`}>
              {done ? <CheckCircle size={14} /> : n}
            </div>
            <span className={`text-sm ${active ? 'text-slate-100' : 'text-slate-500'}`}>{label}</span>
            {i < steps.length - 1 && <div className="w-8 h-px bg-slate-700 mx-1" />}
          </div>
        )
      })}
    </div>
  )
}

export default function OnboardWizard() {
  const navigate = useNavigate()
  const [step, setStep] = useState<Step>(1)
  const [url, setUrl] = useState('')
  const [vertical, setVertical] = useState<'dental' | 'restaurant'>('dental')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [config, setConfig] = useState<any>(null)

  async function handleScrape() {
    if (!url) return
    setLoading(true); setError('')
    try {
      const data = await api.scrapeTenant(url, vertical)
      setConfig(data)
      setStep(2)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleDeploy() {
    setLoading(true); setError('')
    try {
      await api.createTenant(config)
      setStep(3)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  function Field({ label, field, multiline }: { label: string; field: string; multiline?: boolean }) {
    return (
      <div>
        <label className="label">{label}</label>
        {multiline ? (
          <textarea
            rows={3}
            className="input resize-none"
            value={config[field] ?? ''}
            onChange={e => setConfig({ ...config, [field]: e.target.value })}
          />
        ) : (
          <input
            className="input"
            value={config[field] ?? ''}
            onChange={e => setConfig({ ...config, [field]: e.target.value })}
          />
        )}
      </div>
    )
  }

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-semibold text-slate-100 mb-1">Add New Client</h1>
      <p className="text-slate-400 mb-8">Deploy an AI receptionist in 3 minutes — no coding required.</p>

      <StepIndicator current={step} />

      {error && (
        <div className="flex items-center gap-2 text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3 mb-6 text-sm">
          <AlertCircle size={16} /> {error}
        </div>
      )}

      {/* Step 1 — URL */}
      {step === 1 && (
        <div className="card flex flex-col gap-5">
          <div>
            <label className="label">Business type</label>
            <div className="flex gap-3">
              {(['dental', 'restaurant'] as const).map(v => (
                <button
                  key={v}
                  onClick={() => setVertical(v)}
                  className={`flex-1 py-2.5 rounded-lg border text-sm font-medium transition-colors capitalize
                    ${vertical === v
                      ? 'border-indigo-500 bg-indigo-500/10 text-indigo-400'
                      : 'border-slate-700 text-slate-400 hover:border-slate-500'}`}
                >
                  {v === 'dental' ? '🦷 Dental Practice' : '🍽 Restaurant'}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="label">Business website URL</label>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Globe size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  className="input pl-9"
                  placeholder="https://brightsmile dental.com"
                  value={url}
                  onChange={e => setUrl(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleScrape()}
                />
              </div>
              <button className="btn-primary flex items-center gap-2" onClick={handleScrape} disabled={loading || !url}>
                {loading ? <Loader2 size={15} className="animate-spin" /> : <ChevronRight size={15} />}
                {loading ? 'Scanning...' : 'Next'}
              </button>
            </div>
            <p className="text-xs text-slate-500 mt-2">We'll scan the site and pre-fill the configuration for you.</p>
          </div>
        </div>
      )}

      {/* Step 2 — Review */}
      {step === 2 && config && (
        <div className="card flex flex-col gap-5">
          <p className="text-sm text-slate-400">Review and edit the auto-filled details before deploying.</p>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Business name" field="name" />
            <Field label="Client ID (URL-safe)" field="id" />
            <Field label="Location" field="location" />
            <Field label="Phone" field="phone" />
          </div>
          <Field label="Business hours" field="hours" />
          <div>
            <label className="label">Services (one per line)</label>
            <textarea
              rows={4}
              className="input resize-none"
              value={(config.services || []).join('\n')}
              onChange={e => setConfig({ ...config, services: e.target.value.split('\n').filter(Boolean) })}
            />
          </div>
          {config.emergency_triage !== undefined && (
            <Field label="Emergency triage rule" field="emergency_triage" multiline />
          )}
          <Field label="Human handoff rule" field="human_handoff" multiline />

          <div className="flex gap-3 pt-2">
            <button className="btn-ghost" onClick={() => setStep(1)}>Back</button>
            <button className="btn-primary flex items-center gap-2 ml-auto" onClick={handleDeploy} disabled={loading}>
              {loading ? <Loader2 size={15} className="animate-spin" /> : null}
              {loading ? 'Deploying...' : 'Deploy Receptionist'}
            </button>
          </div>
        </div>
      )}

      {/* Step 3 — Done */}
      {step === 3 && config && (
        <div className="card flex flex-col items-center gap-5 py-10 text-center">
          <div className="w-14 h-14 bg-emerald-500/10 rounded-full flex items-center justify-center">
            <CheckCircle size={28} className="text-emerald-400" />
          </div>
          <div>
            <h2 className="text-xl font-semibold text-slate-100">{config.name} is live</h2>
            <p className="text-slate-400 mt-1">Your AI receptionist is deployed and ready to answer calls.</p>
          </div>
          <div className="bg-slate-900 rounded-lg px-6 py-3 border border-slate-700 font-mono text-sm text-slate-300">
            uv run bot.py --tenant {config.id}
          </div>
          <button className="btn-primary" onClick={() => navigate(`/${config.id}/calls`)}>
            Go to Dashboard
          </button>
        </div>
      )}
    </div>
  )
}
