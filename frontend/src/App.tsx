import { Routes, Route, NavLink, useParams } from 'react-router-dom'
import { Phone, LayoutDashboard, Settings, PlusCircle, Mic } from 'lucide-react'
import { clsx } from 'clsx'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import OnboardWizard from './pages/OnboardWizard'
import CallLog from './pages/CallLog'
import CallDetail from './pages/CallDetail'
import TenantSettings from './pages/TenantSettings'

function Sidebar({ tenantId }: { tenantId?: string }) {
  const navItem = (to: string, icon: React.ReactNode, label: string) => (
    <NavLink
      to={to}
      className={({ isActive }) =>
        clsx('flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors',
          isActive
            ? 'bg-indigo-500/10 text-indigo-400 font-medium'
            : 'text-slate-400 hover:text-slate-100 hover:bg-slate-700/50')
      }
    >
      {icon}
      {label}
    </NavLink>
  )

  return (
    <aside className="w-60 shrink-0 bg-slate-800/50 border-r border-slate-700 flex flex-col p-4 gap-1">
      <div className="flex items-center gap-2 px-3 py-3 mb-4">
        <div className="w-7 h-7 bg-indigo-500 rounded-lg flex items-center justify-center">
          <Mic size={14} className="text-white" />
        </div>
        <span className="font-semibold text-slate-100 text-sm">Skove AI</span>
      </div>

      {navItem('/onboard', <PlusCircle size={16} />, 'New Client')}

      {tenantId && (
        <>
          <div className="mt-4 mb-1 px-3 text-xs text-slate-500 uppercase tracking-wider">Current client</div>
          {navItem(`/${tenantId}/calls`, <LayoutDashboard size={16} />, 'Call Log')}
          {navItem(`/${tenantId}/settings`, <Settings size={16} />, 'Settings')}
        </>
      )}
    </aside>
  )
}

function TenantLayout() {
  const { tenantId } = useParams<{ tenantId: string }>()
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar tenantId={tenantId} />
      <main className="flex-1 overflow-y-auto p-8">
        <Routes>
          <Route path="calls" element={<CallLog />} />
          <Route path="calls/:callId" element={<CallDetail />} />
          <Route path="settings" element={<TenantSettings />} />
        </Routes>
      </main>
    </div>
  )
}

function Landing() {
  const { data: tenants } = useQuery({ queryKey: ['tenants'], queryFn: api.listTenants })

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 flex flex-col items-center justify-center gap-6 p-8">
        <div className="text-center">
          <h1 className="text-3xl font-semibold text-slate-100 mb-2">AI Receptionist Platform</h1>
          <p className="text-slate-400">Deploy an AI receptionist for any business in 3 minutes.</p>
        </div>

        {tenants && tenants.length > 0 && (
          <div className="w-full max-w-md">
            <p className="label mb-3">Select a client</p>
            <div className="flex flex-col gap-2">
              {tenants.map((t: any) => (
                <NavLink
                  key={t.id}
                  to={`/${t.id}/calls`}
                  className="card hover:border-indigo-500/50 transition-colors cursor-pointer flex items-center justify-between"
                >
                  <div>
                    <p className="font-medium text-slate-100">{t.name}</p>
                    <p className="text-xs text-slate-400 mt-0.5 capitalize">{t.vertical} · {t.location || 'Location not set'}</p>
                  </div>
                  <Phone size={16} className="text-slate-500" />
                </NavLink>
              ))}
            </div>
          </div>
        )}

        <NavLink to="/onboard" className="btn-primary flex items-center gap-2">
          <PlusCircle size={16} /> Add new client
        </NavLink>
      </main>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/onboard" element={
        <div className="flex h-screen overflow-hidden">
          <Sidebar />
          <main className="flex-1 overflow-y-auto p-8"><OnboardWizard /></main>
        </div>
      } />
      <Route path="/:tenantId/*" element={<TenantLayout />} />
    </Routes>
  )
}
