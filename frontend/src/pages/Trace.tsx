import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, statusColor, type Trace } from '../lib/api'

const STEP_COLOR: Record<string, string> = {
  plan: 'border-cyan-500',
  retrieve: 'border-sky-500',
  analyze: 'border-amber-500',
  sql: 'border-indigo-500',
  tool: 'border-violet-500',
  validate: 'border-emerald-500',
  correct: 'border-rose-500',
  report: 'border-fuchsia-500',
}

export default function Trace() {
  const { taskId } = useParams()
  const nav = useNavigate()
  const [tasks, setTasks] = useState<{ id: string; title: string; status: string }[]>([])
  const [trace, setTrace] = useState<Trace | null>(null)
  const [error, setError] = useState('')

  useEffect(() => { api.tasks().then((t) => setTasks(t.slice(0, 25))).catch(() => {}) }, [])

  const load = useCallback(() => {
    if (!taskId) { setTrace(null); return }
    api.trace(taskId).then(setTrace).catch((e) => setError(String(e.message || e)))
  }, [taskId])

  useEffect(() => {
    load()
    const t = setInterval(load, 4000)
    return () => clearInterval(t)
  }, [load])

  return (
    <div className="p-6 grid grid-cols-[260px_1fr] gap-6 h-screen">
      <aside className="overflow-y-auto">
        <h1 className="text-lg font-semibold mb-3">Task Trace</h1>
        <div className="space-y-1">
          {tasks.map((t) => (
            <button
              key={t.id}
              onClick={() => nav(`/trace/${t.id}`)}
              className={`w-full text-left px-3 py-2 rounded-lg text-xs border ${
                t.id === taskId ? 'border-cyan-600 bg-cyan-600/10' : 'border-slate-800 hover:bg-slate-900'
              }`}
            >
              <div className="truncate text-slate-200">{t.title || t.id.slice(0, 8)}</div>
              <span className={`badge ${statusColor(t.status)} mt-1`}>{t.status}</span>
            </button>
          ))}
        </div>
      </aside>

      <section className="overflow-y-auto pr-2">
        {!taskId && <div className="text-slate-500 text-sm">Select a task to inspect its execution timeline.</div>}
        {error && <div className="text-rose-400 text-sm">{error}</div>}
        {trace && (
          <div className="space-y-6">
            <div className="card flex flex-wrap items-center gap-4">
              <div>
                <div className="text-xs text-slate-400">Trace ID</div>
                <div className="font-mono text-sm text-cyan-300">{trace.trace_id}</div>
              </div>
              <div>
                <div className="text-xs text-slate-400">Status</div>
                <span className={`badge ${statusColor(trace.status)}`}>{trace.status}</span>
              </div>
              <div>
                <div className="text-xs text-slate-400">Confidence</div>
                <div className="text-sm">{trace.confidence ?? '—'}</div>
              </div>
              <div>
                <div className="text-xs text-slate-400">Retries</div>
                <div className="text-sm">{trace.retry_count}</div>
              </div>
            </div>

            {trace.plan != null && (
              <div className="card">
                <h2 className="text-sm font-medium text-slate-300 mb-2">Plan</h2>
                <pre className="text-xs text-slate-400 overflow-x-auto">{JSON.stringify(trace.plan, null, 2)}</pre>
              </div>
            )}

            <div className="card">
              <h2 className="text-sm font-medium text-slate-300 mb-4">Execution timeline</h2>
              <ol className="space-y-3">
                {trace.timeline.map((s) => (
                  <li key={s.sequence} className={`border-l-2 pl-4 ${STEP_COLOR[s.step_type] || 'border-slate-600'}`}>
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <span className="text-slate-500">#{s.sequence}</span>
                      <span className="font-medium text-white">{s.agent}</span>
                      <span className="badge bg-slate-800 text-slate-300">{s.step_type}</span>
                      <span className={`badge ${statusColor(s.status)}`}>{s.status}</span>
                      <span className="text-slate-500">{s.latency_ms}ms</span>
                    </div>
                    {s.error && <div className="text-rose-400 text-xs mt-1">{s.error}</div>}
                    <details className="mt-1">
                      <summary className="text-xs text-slate-500 cursor-pointer">details</summary>
                      <div className="grid md:grid-cols-2 gap-2 mt-1">
                        <pre className="text-[10px] bg-slate-950 rounded p-2 overflow-x-auto max-h-48">{JSON.stringify(s.input, null, 1)}</pre>
                        <pre className="text-[10px] bg-slate-950 rounded p-2 overflow-x-auto max-h-48">{JSON.stringify(s.output, null, 1)}</pre>
                      </div>
                    </details>
                  </li>
                ))}
                {!trace.timeline.length && <div className="text-slate-500 text-sm">No steps recorded yet.</div>}
              </ol>
            </div>

            {trace.corrections.length > 0 && (
              <div className="card border-rose-900/50">
                <h2 className="text-sm font-medium text-rose-300 mb-2">Self-corrections ({trace.corrections.length})</h2>
                <div className="space-y-2">
                  {trace.corrections.map((c, i) => (
                    <div key={i} className="text-xs bg-rose-950/30 border border-rose-900/40 rounded p-3">
                      <div className="flex gap-2 mb-1">
                        <span className="badge bg-rose-500/20 text-rose-300">{c.failure_category}</span>
                        <span className="badge bg-amber-500/15 text-amber-300">strategy: {c.strategy}</span>
                      </div>
                      <div className="text-slate-400">{c.description}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {trace.validations.length > 0 && (
              <div className="card">
                <h2 className="text-sm font-medium text-slate-300 mb-2">Validation</h2>
                {trace.validations.map((v, i) => (
                  <div key={i} className="text-xs mb-2 border-b border-slate-800 pb-2">
                    <span className={`badge ${v.passed ? 'bg-emerald-500/15 text-emerald-300' : 'bg-rose-500/15 text-rose-300'}`}>
                      {v.passed ? 'PASSED' : 'FAILED'}
                    </span>{' '}
                    <span className="text-slate-400">score {v.score}</span>
                    {v.issues?.length > 0 && <div className="text-amber-300 mt-1">Issues: {v.issues.join('; ')}</div>}
                    {v.unsupported_claims?.length > 0 && (
                      <div className="text-rose-300 mt-1">Unsupported: {v.unsupported_claims.slice(0, 3).join(' | ')}</div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {trace.tool_calls.length > 0 && (
              <div className="card">
                <h2 className="text-sm font-medium text-slate-300 mb-2">Tool calls</h2>
                <table className="w-full">
                  <thead><tr><th className="table-th">Tool</th><th className="table-th">Agent</th><th className="table-th">Risk</th><th className="table-th">Status</th><th className="table-th">ms</th></tr></thead>
                  <tbody>
                    {trace.tool_calls.map((t, i) => (
                      <tr key={i}>
                        <td className="table-td">{t.tool}</td>
                        <td className="table-td">{t.agent}</td>
                        <td className="table-td">{t.risk_level}</td>
                        <td className="table-td"><span className={`badge ${statusColor(t.status)}`}>{t.status}</span></td>
                        <td className="table-td">{t.latency_ms}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {trace.evidence.length > 0 && (
              <div className="card">
                <h2 className="text-sm font-medium text-slate-300 mb-2">Evidence & sources</h2>
                <div className="space-y-2">
                  {trace.evidence.map((e, i) => (
                    <div key={i} className="text-xs border border-slate-800 rounded p-3">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="badge bg-cyan-500/10 text-cyan-300">{e.source_ref}</span>
                        <span className="text-slate-500">strength {e.strength.toFixed(2)}</span>
                      </div>
                      <div className="text-slate-400 line-clamp-3">{e.excerpt}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  )
}
