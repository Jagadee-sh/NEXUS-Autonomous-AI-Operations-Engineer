import { useEffect, useState } from 'react'
import { api, type AgentInfo } from '../lib/api'

export default function Agents() {
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [error, setError] = useState('')

  useEffect(() => { api.agents().then(setAgents).catch((e) => setError(String(e.message || e))) }, [])

  return (
    <div className="p-6 space-y-4">
      <header>
        <h1 className="text-xl font-semibold">Agents</h1>
        <p className="text-sm text-slate-400">Explicit responsibilities, tools, and observed performance.</p>
      </header>
      {error && <div className="text-rose-400 text-sm">{error}</div>}
      <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
        {agents.map((a) => (
          <div key={a.name} className="card flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <div className="font-medium text-white">{a.role}</div>
              <span className={`badge ${a.is_active ? 'bg-emerald-500/15 text-emerald-300' : 'bg-slate-700 text-slate-400'}`}>
                {a.is_active ? 'active' : 'inactive'}
              </span>
            </div>
            <p className="text-xs text-slate-400 leading-relaxed flex-1">{a.description}</p>
            <div className="flex flex-wrap gap-1">
              {a.tools.length === 0 && <span className="badge bg-slate-800 text-slate-500">no direct tools</span>}
              {a.tools.map((t) => (
                <span key={t} className="badge bg-cyan-500/10 text-cyan-300">{t}</span>
              ))}
            </div>
            <div className="text-xs text-slate-500 flex justify-between border-t border-slate-800 pt-2">
              <span>{a.recent_executions} recent executions</span>
              <span>{a.success_rate != null ? `${Math.round(a.success_rate * 100)}% success` : 'no data'}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
