const BASE = 'http://localhost:8000'

async function req<T>(path: string, opts?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }))
    throw new Error(err.detail ?? r.statusText)
  }
  return r.json()
}

export const api = {
  listTenants: () => req<any[]>('/api/tenants'),
  getTenant: (id: string) => req<any>(`/api/tenants/${id}`),
  createTenant: (body: any) => req<any>('/api/tenants', { method: 'POST', body: JSON.stringify(body) }),
  updateTenant: (id: string, body: any) => req<any>(`/api/tenants/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  scrapeTenant: (url: string, vertical: string) =>
    req<any>('/api/tenants/scrape', { method: 'POST', body: JSON.stringify({ url, vertical }) }),
  listCalls: (tenantId: string) => req<any[]>(`/api/tenants/${tenantId}/calls`),
  getCall: (callId: string) => req<any>(`/api/calls/${callId}`),
  recordingUrl: (callId: string) => `${BASE}/api/calls/${callId}/recording`,
}
