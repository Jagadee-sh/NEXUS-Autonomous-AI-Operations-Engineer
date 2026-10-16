import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, statusColor, type Stats } from '../lib/api'

function Metric({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="card">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="text-2xl font-semibold mt-1 text-white">{value}</div>
      {hint && <div className="text-xs text-slate-500 mt-1">{hint}</div>}
    </div>
  )
}

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    const load = () => api.stats().then((s) => alive && setStats(s)).catch((e) => alive && setError(String(e.message || e)))
    load()
    const t = setInterval(load, 5000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  if (error) return <div className="p-6 text-rose-400">Failed to load dashboard: {error}</div>
  if (!stats) return <div className="p-6 text-slate-400">Loading…</div>

  const statusEntries = Object.entries(stats.tasks_by_status)

  return (
    <div className="p-6 space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Dashboard</h1>
          <p className="text-sm text-slate-400">Autonomous agent execution overview</p>
        </div>
        <Link to="/workspace" className="btn-primary">New Task →</Link>
      </header>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Metric label="Tasks" value={stats.tasks_total} hint={statusEntries.map(([k, v]) => `${k}:${v}`).join(' · ') || 'none yet'} />
        <Metric label="Success rate" value={stats.success_rate == null ? '—' : `${Math.round(stats.success_rate * 100)}%`} />
        <Metric label="Avg confidence" value={stats.avg_confidence ?? '—'} />
        <Metric label="Avg latency" value={stats.avg_latency_seconds != null ? `${stats.avg_latency_seconds}s` : '—'} />
        <Metric label="Documents ready" value={`${stats.documents.ready}/${stats.documents.total}`} />
        <Metric label="Datasets" value={stats.datasets} />
        <Metric label="Pending approvals" value={stats.pending_approvals} />
        <Metric label="Providers" value={stats.llm_provider} hint={`${stats.embedding_provider} · ${stats.vector_store}`} />
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="card">
          <h2 className="text-sm font-medium text-slate-300 mb-3">Recent executions</h2>
          <table className="w-full">
            <thead><tr><th className="table-th">Task</th><th className="table-th">Status</th><th className="table-th">Conf.</th><th className="table-th">Trace</th></tr></thead>
            <tbody>
              {stats.recent_tasks.map((t) => (
                <tr key={t.id}>
                  <td className="table-td max-w-[280px] truncate">{t.title}</td>
                  <td className="table-td"><span className={`badge ${statusColor(t.status)}`}>{t.status}</span></td>
                  <td className="table-td">{t.confidence ?? '—'}</td>
                  <td className="table-td">
                    <Link className="text-cyan-400 hover:underline" to={`/trace/${t.id}`}>view</Link>
                  </td>
                </tr>
              ))}
              {!stats.recent_tasks.length && <tr><td className="table-td text-slate-500" colSpan={4}>No tasks yet — try the AI Workspace.</td></tr>}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h2 className="text-sm font-medium text-slate-300 mb-3">Agent pipeline</h2>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            {['Planner', 'Router', 'Data/SQL/Research', 'Validator', 'Self-Correct', 'Report'].map((s, i) => (
              <span key={s} className="flex items-center gap-2">
                <span className="badge bg-slate-800 text-slate-300">{s}</span>
                {i < 5 && <span className="text-slate-600">→</span>}
              </span>
            ))}
          </div>
          <p className="text-xs text-slate-500 mt-4">
            Every task records plan → agent steps → tool calls → validation → corrections → final report under a trace ID.
            Open Task Trace to inspect the full timeline.
          </p>
        </div>
      </div>
    </div>
  )
}
