import { useEffect, useState } from 'react'
import { statusColor } from '../lib/api'

type HealthBody = { status: string; version: string; time: string }
type ReadyBody = { status: string; checks: Record<string, string> }

export default function Health() {
  const [health, setHealth] = useState<HealthBody | null>(null)
  const [ready, setReady] = useState<ReadyBody | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    const load = () => {
      Promise.all([
        fetch('/health').then((r) => r.json()),
        fetch('/ready').then((r) => r.json()),
      ])
        .then(([h, r]) => { setHealth(h); setReady(r) })
        .catch((e) => setError(String(e)))
    }
    load()
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [])

  return (
    <div className="p-6 space-y-6">
      <header>
        <h1 className="text-xl font-semibold">System Health</h1>
        <p className="text-sm text-slate-400">Live dependency readiness, refreshed every 5s.</p>
      </header>
      {error && <div className="text-rose-400 text-sm">{error}</div>}

      <div className="grid md:grid-cols-2 gap-4">
        <div className="card">
          <div className="text-xs text-slate-400">API</div>
          <div className="flex items-center gap-2 mt-1">
            <span className={`badge ${statusColor(health?.status || '')}`}>{health?.status || '…'}</span>
            <span className="text-xs text-slate-500">v{health?.version}</span>
          </div>
          {health && <div className="text-[10px] text-slate-600 mt-1">{new Date(health.time).toLocaleString()}</div>}
        </div>
        <div className="card">
          <div className="text-xs text-slate-400">Readiness</div>
          <div className={`badge ${statusColor(ready?.status || '')} mt-1`}>{ready?.status || '…'}</div>
        </div>
      </div>

      <div className="card">
        <h2 className="text-sm font-medium text-slate-300 mb-3">Dependencies</h2>
        <table className="w-full">
          <thead><tr><th className="table-th">Component</th><th className="table-th">Status</th></tr></thead>
          <tbody>
            {ready &&
              Object.entries(ready.checks).map(([k, v]) => (
                <tr key={k}>
                  <td className="table-td">{k}</td>
                  <td className="table-td">
                    <span className={`badge ${statusColor(String(v))}`}>{String(v)}</span>
                  </td>
                </tr>
              ))}
            {!ready && <tr><td className="table-td text-slate-500" colSpan={2}>Loading…</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}
