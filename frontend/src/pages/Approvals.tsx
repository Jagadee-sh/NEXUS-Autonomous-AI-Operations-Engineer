import { useEffect, useState } from 'react'
import { api, statusColor, type Approval } from '../lib/api'

export default function Approvals() {
  const [pending, setPending] = useState<Approval[]>([])
  const [decided, setDecided] = useState<Approval[]>([])
  const [msg, setMsg] = useState('')

  const reload = () => {
    api.approvals('pending').then(setPending).catch(() => {})
    api.approvals('approved').then((a) =>
      api.approvals('rejected').then((r) => setDecided([...a, ...r].slice(0, 20))).catch(() => setDecided(a)),
    ).catch(() => {})
  }
  useEffect(reload, [])

  const decide = async (id: string, action: 'approve' | 'reject') => {
    try {
      if (action === 'approve') await api.approve(id, 'Reviewed in UI')
      else await api.reject(id, 'Rejected in UI')
      setMsg(`Request ${action}d`)
      reload()
    } catch (e) {
      setMsg(`Failed: ${(e as Error).message}`)
    }
  }

  return (
    <div className="p-6 space-y-6">
      <header>
        <h1 className="text-xl font-semibold">Approvals</h1>
        <p className="text-sm text-slate-400">HIGH / CRITICAL actions pause for human review before execution.</p>
      </header>
      {msg && <div className="text-sm text-cyan-300">{msg}</div>}

      <div className="card">
        <h2 className="text-sm font-medium text-slate-300 mb-3">Pending ({pending.length})</h2>
        <div className="space-y-3">
          {pending.map((a) => (
            <div key={a.id} className="border border-slate-800 rounded-lg p-4 flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm text-white">{a.action}</span>
                  <span className={`badge ${a.risk_level === 'CRITICAL' ? 'bg-rose-500/20 text-rose-300' : 'bg-amber-500/15 text-amber-300'}`}>{a.risk_level}</span>
                  <span className="badge bg-slate-800 text-slate-400">{a.requested_by}</span>
                </div>
                <pre className="text-[10px] text-slate-500 mt-2 max-w-xl overflow-x-auto">{JSON.stringify(a.payload, null, 1)}</pre>
                <div className="text-[10px] text-slate-600 mt-1">{new Date(a.created_at).toLocaleString()}</div>
              </div>
              <div className="flex gap-2 shrink-0">
                <button className="btn-primary !py-1" onClick={() => decide(a.id, 'approve')}>Approve</button>
                <button className="btn bg-rose-700 hover:bg-rose-600 text-white !py-1" onClick={() => decide(a.id, 'reject')}>Reject</button>
              </div>
            </div>
          ))}
          {!pending.length && <div className="text-sm text-slate-500">Nothing awaiting approval.</div>}
        </div>
      </div>

      <div className="card">
        <h2 className="text-sm font-medium text-slate-300 mb-3">Recently decided</h2>
        <table className="w-full">
          <thead><tr><th className="table-th">Action</th><th className="table-th">Risk</th><th className="table-th">Decision</th><th className="table-th">Reason</th></tr></thead>
          <tbody>
            {decided.map((a) => (
              <tr key={a.id}>
                <td className="table-td">{a.action}</td>
                <td className="table-td">{a.risk_level}</td>
                <td className="table-td"><span className={`badge ${statusColor(a.status)}`}>{a.status}</span></td>
                <td className="table-td text-xs text-slate-400">{a.reason || '—'}</td>
              </tr>
            ))}
            {!decided.length && <tr><td className="table-td text-slate-500" colSpan={4}>No decisions yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}
