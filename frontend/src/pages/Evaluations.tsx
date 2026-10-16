import { useEffect, useState } from 'react'
import { api, statusColor, type EvalDataset, type EvalRun } from '../lib/api'

export default function Evaluations() {
  const [datasets, setDatasets] = useState<EvalDataset[]>([])
  const [runs, setRuns] = useState<EvalRun[]>([])
  const [research, setResearch] = useState<EvalRun | null>(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState('')

  const reload = () => {
    api.evalDatasets().then(setDatasets).catch(() => {})
    api.evalRuns().then(setRuns).catch(() => {})
    api.latestResearch().then(setResearch).catch(() => {})
  }
  useEffect(reload, [])

  const run = async (id: string) => {
    setBusy(id)
    setMsg('Running evaluation…')
    try {
      const r = await api.runEval(id)
      setMsg(`Run complete — faithfulness ${r.metrics.faithfulness ?? '—'}, correctness ${r.metrics.answer_correctness ?? '—'}, success ${r.metrics.task_success_rate}`)
      reload()
    } catch (e) {
      setMsg(`Run failed: ${(e as Error).message}`)
    } finally {
      setBusy('')
    }
  }

  const createQuick = async () => {
    try {
      await api.createEvalDataset({
        name: `Smoke ${new Date().toLocaleTimeString()}`,
        description: 'Quick deterministic evaluation',
        items: [
          {
            id: 'q1',
            question: 'What travel amount requires VP approval according to the policy documents?',
            expected_answer: 'Travel above 2000 requires VP approval',
            expected_sources: ['business_policy.pdf'],
          },
        ],
      })
      reload()
    } catch (e) {
      setMsg(`Create failed: ${(e as Error).message}`)
    }
  }

  const lastRun = runs.find((r) => !research || r.id !== research.id)

  const runResearch = async () => {
    setBusy('research')
    setMsg('Running retrieval strategy experiment (vector vs keyword vs hybrid)…')
    try {
      const r = await api.startResearch({ dataset_id: datasets[0]?.id })
      setResearch(r)
      setMsg(`Research complete — best strategy: ${r.metrics.best_strategy ?? '—'}`)
      reload()
    } catch (e) {
      setMsg(`Research failed: ${(e as Error).message}`)
    } finally {
      setBusy('')
    }
  }

  const strategies = ['vector', 'keyword', 'hybrid'] as const

  return (
    <div className="p-6 space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Evaluations</h1>
          <p className="text-sm text-slate-400">Datasets → agent runs → metrics → version comparison.</p>
        </div>
        <button className="btn-ghost" onClick={createQuick}>+ Quick dataset</button>
      </header>
      {msg && <div className="text-sm text-cyan-300">{msg}</div>}

      {lastRun && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          {[
            ['Faithfulness', lastRun.metrics.faithfulness],
            ['Correctness', lastRun.metrics.answer_correctness],
            ['Retrieval rel.', lastRun.metrics.retrieval_relevance],
            ['Task success', lastRun.metrics.task_success_rate],
            ['Avg latency', lastRun.metrics.latency_seconds],
          ].map(([label, val]) => (
            <div key={String(label)} className="card">
              <div className="text-xs text-slate-400">{label}</div>
              <div className="text-xl font-semibold text-white">{val ?? '—'}</div>
            </div>
          ))}
        </div>
      )}

      <div className="grid lg:grid-cols-2 gap-6">
        <div className="card">
          <h2 className="text-sm font-medium text-slate-300 mb-3">Evaluation datasets</h2>
          <table className="w-full">
            <thead><tr><th className="table-th">Name</th><th className="table-th">Items</th><th className="table-th"></th></tr></thead>
            <tbody>
              {datasets.map((d) => (
                <tr key={d.id}>
                  <td className="table-td">{d.name}<div className="text-[10px] text-slate-500">{d.description}</div></td>
                  <td className="table-td">{d.items.length}</td>
                  <td className="table-td text-right">
                    <button className="btn-primary !py-1 !text-xs" onClick={() => run(d.id)} disabled={busy === d.id}>
                      {busy === d.id ? 'Running…' : 'Run'}
                    </button>
                  </td>
                </tr>
              ))}
              {!datasets.length && <tr><td className="table-td text-slate-500" colSpan={3}>No datasets.</td></tr>}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h2 className="text-sm font-medium text-slate-300 mb-3">Runs</h2>
          <table className="w-full">
            <thead><tr><th className="table-th">Status</th><th className="table-th">Faithfulness</th><th className="table-th">Success</th><th className="table-th">When</th></tr></thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id}>
                  <td className="table-td"><span className={`badge ${statusColor(r.status)}`}>{r.status}</span></td>
                  <td className="table-td">{r.metrics.faithfulness ?? '—'}</td>
                  <td className="table-td">{r.metrics.task_success_rate ?? '—'}</td>
                  <td className="table-td text-xs text-slate-500">{new Date(r.created_at).toLocaleString()}</td>
                </tr>
              ))}
              {!runs.length && <tr><td className="table-td text-slate-500" colSpan={4}>No runs yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-sm font-medium text-slate-300">Research: retrieval strategy comparison</h2>
            <p className="text-xs text-slate-500">
              Controlled experiment over evaluation items — vector vs keyword vs hybrid, scored per strategy.
            </p>
          </div>
          <button className="btn-primary !py-1 !text-xs" onClick={runResearch} disabled={busy === 'research'}>
            {busy === 'research' ? 'Experimenting…' : 'Run experiment'}
          </button>
        </div>
        {research ? (
          <table className="w-full">
            <thead>
              <tr>
                <th className="table-th">Strategy</th>
                <th className="table-th">Combined</th>
                <th className="table-th">Relevance</th>
                <th className="table-th">Content recall</th>
                <th className="table-th">Hit rate</th>
                <th className="table-th">Latency ms</th>
              </tr>
            </thead>
            <tbody>
              {strategies.map((s) => {
                const m = research.metrics
                const best = m.best_strategy === s
                return (
                  <tr key={s} className={best ? 'bg-cyan-500/5' : ''}>
                    <td className="table-td font-medium">
                      {s}{best && <span className="badge bg-cyan-500/15 text-cyan-300 ml-2">best</span>}
                    </td>
                    <td className="table-td">{m[`${s}_combined`] ?? '—'}</td>
                    <td className="table-td">{m[`${s}_relevance`] ?? '—'}</td>
                    <td className="table-td">{m[`${s}_content_recall`] ?? '—'}</td>
                    <td className="table-td">{m[`${s}_hit_rate`] ?? '—'}</td>
                    <td className="table-td">{m[`${s}_latency_ms`] ?? '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        ) : (
          <div className="text-xs text-slate-500">No experiment run yet.</div>
        )}
      </div>
    </div>
  )
}
