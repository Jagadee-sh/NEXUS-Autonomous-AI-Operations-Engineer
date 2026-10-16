import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, statusColor, type Dataset, type Document, type Task, type Trace } from '../lib/api'

type Msg = {
  role: 'user' | 'assistant'
  text: string
  taskId?: string
  citations?: string[]
  confidence?: number
  corrections?: number
}

type Live = {
  taskId: string
  status: string
  steps: Trace['timeline']
  validations: Trace['validations']
  corrections: Trace['corrections']
}

const TERMINAL = new Set(['succeeded', 'failed', 'cancelled'])

export default function Workspace() {
  const [docs, setDocs] = useState<Document[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [selDocs, setSelDocs] = useState<string[]>([])
  const [selData, setSelData] = useState<string[]>([])
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Msg[]>([])
  const [busy, setBusy] = useState(false)
  const [live, setLive] = useState<Live | null>(null)
  const [simulate, setSimulate] = useState(false)
  const [error, setError] = useState('')
  const [recent, setRecent] = useState<Task[]>([])
  const bottom = useRef<HTMLDivElement>(null)
  const timer = useRef<number | null>(null)

  const stopPoll = () => {
    if (timer.current !== null) {
      window.clearInterval(timer.current)
      timer.current = null
    }
  }
  useEffect(() => stopPoll, [])

  const reload = () => {
    api.documents().then(setDocs).catch(() => {})
    api.datasets().then(setDatasets).catch(() => {})
    api.tasks().then((t) => setRecent(t.slice(0, 6))).catch(() => {})
  }
  useEffect(reload, [])

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, busy, live])

  const submit = async () => {
    const question = input.trim()
    if (!question || busy) return
    setBusy(true)
    setError('')
    setInput('')
    setMessages((m) => [...m, { role: 'user', text: question }])
    try {
      const res = await api.query({
        question,
        document_ids: selDocs,
        dataset_ids: selData,
        wait: false,
        failure_injection: simulate ? { category: 'poor_retrieval', fail_first: 1 } : null,
      })
      setLive({ taskId: res.task_id, status: 'queued', steps: [], validations: [], corrections: [] })
      timer.current = window.setInterval(async () => {
        try {
          const [tr, tk] = await Promise.all([api.trace(res.task_id), api.task(res.task_id)])
          setLive((l) =>
            l && l.taskId === res.task_id
              ? { ...l, status: tk.status, steps: tr.timeline, validations: tr.validations, corrections: tr.corrections }
              : l,
          )
          if (TERMINAL.has(tk.status)) {
            stopPoll()
            const r = tk.result || {}
            setMessages((m) => [
              ...m,
              {
                role: 'assistant',
                text: r.answer || (tk.error ? `⚠ Task failed: ${tk.error}` : '(no answer produced)'),
                taskId: tk.id,
                confidence: tk.confidence ?? undefined,
                citations: r.citations || [],
                corrections: (r.corrections || []).length,
              },
            ])
            setLive(null)
            setBusy(false)
            reload()
          }
        } catch {
          /* transient polling error — keep trying */
        }
      }, 1500)
    } catch (e) {
      setError(String((e as Error).message || e))
      setMessages((m) => [...m, { role: 'assistant', text: `⚠ Task failed: ${(e as Error).message}` }])
      setLive(null)
      setBusy(false)
    }
  }

  const toggle = (arr: string[], set: (v: string[]) => void, id: string) =>
    set(arr.includes(id) ? arr.filter((x) => x !== id) : [...arr, id])

  return (
    <div className="p-6 h-screen flex flex-col">
      <header className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-semibold">AI Workspace</h1>
          <p className="text-sm text-slate-400">Submit complex tasks — planner, agents, validation and correction run live.</p>
        </div>
        <div className="text-xs text-slate-500">
          {selDocs.length} docs · {selData.length} datasets selected
        </div>
      </header>

      <div className="grid grid-cols-3 gap-4 mb-4 max-h-40 overflow-y-auto">
        <div className="card">
          <div className="text-xs text-slate-400 mb-2">Documents</div>
          {docs.length === 0 && <div className="text-xs text-slate-600">Upload in Knowledge</div>}
          {docs.map((d) => (
            <label key={d.id} className="flex items-center gap-2 text-xs py-0.5 cursor-pointer">
              <input type="checkbox" checked={selDocs.includes(d.id)} onChange={() => toggle(selDocs, setSelDocs, d.id)} />
              <span className="truncate">{d.filename}</span>
              <span className={`badge ${statusColor(d.status)} ml-auto`}>{d.status}</span>
            </label>
          ))}
        </div>
        <div className="card">
          <div className="text-xs text-slate-400 mb-2">Datasets</div>
          {datasets.length === 0 && <div className="text-xs text-slate-600">Upload in Knowledge</div>}
          {datasets.map((d) => (
            <label key={d.id} className="flex items-center gap-2 text-xs py-0.5 cursor-pointer">
              <input type="checkbox" checked={selData.includes(d.id)} onChange={() => toggle(selData, setSelData, d.id)} />
              <span className="truncate">{d.name}</span>
              <span className="text-slate-500 ml-auto">{d.row_count} rows</span>
            </label>
          ))}
        </div>
        <div className="card text-xs text-slate-400 leading-relaxed">
          <div className="text-slate-300 font-medium mb-1">Try the flagship demo</div>
          “Analyze why profitability declined in Q3. Compare Q2 and Q3, identify the top three contributing
          factors, verify findings using company documents, and provide three recommended actions.”
          <div className="mt-2"><Link className="text-cyan-400 hover:underline" to="/knowledge">→ Load demo data first</Link></div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto space-y-4 pb-4">
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
            <div className={`max-w-[75%] rounded-xl px-4 py-3 text-sm whitespace-pre-wrap ${m.role === 'user' ? 'bg-cyan-600/20 border border-cyan-700/40' : 'bg-slate-900 border border-slate-800'}`}>
              {m.text}
              {m.role === 'assistant' && m.citations && m.citations.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {m.citations.slice(0, 6).map((c, ci) => (
                    <span key={ci} className="badge bg-cyan-500/10 text-cyan-300 text-[10px]">{c}</span>
                  ))}
                </div>
              )}
              {m.role === 'assistant' && (
                <div className="mt-3 flex items-center gap-3 text-xs">
                  {m.taskId && (
                    <Link className="text-cyan-400 hover:underline" to={`/trace/${m.taskId}`}>Inspect full trace →</Link>
                  )}
                  {m.confidence != null && <span className="text-slate-400">confidence {m.confidence}</span>}
                  {!!m.corrections && (
                    <span className="text-amber-300">self-corrected ×{m.corrections}</span>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
        {busy && (
          <div className="card max-w-[75%] text-xs space-y-1 bg-slate-950/70">
            <div className="flex items-center gap-2 text-slate-300 font-medium">
              <span className="inline-block w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
              {live ? `Executing — ${live.status} · ${live.steps.length} steps observed` : 'Submitting task…'}
            </div>
            {live?.steps.map((s) => (
              <div key={s.sequence} className="flex items-center gap-2 text-slate-400">
                <span className={`badge text-[10px] ${statusColor(s.status)}`}>{s.status}</span>
                <span className="text-slate-300">{s.agent}</span>
                <span className="text-slate-500">{s.step_type}</span>
                <span className="text-slate-600">{s.latency_ms}ms</span>
                {s.error && <span className="text-rose-400 truncate">{s.error.slice(0, 80)}</span>}
              </div>
            ))}
            {live?.validations.map((v, i) => (
              <div key={`v${i}`} className={v.passed ? 'text-emerald-400' : 'text-amber-400'}>
                validation #{i + 1}: {v.passed ? 'passed' : 'failed'} (score {v.score.toFixed(2)})
                {!v.passed && v.issues[0] && ` — ${v.issues[0].slice(0, 90)}`}
              </div>
            ))}
            {live?.corrections.map((c, i) => (
              <div key={`c${i}`} className="text-amber-300">
                self-correction #{i + 1}: {c.failure_category} → {c.strategy} {c.succeeded ? '✓ recovered' : '✗'}
              </div>
            ))}
          </div>
        )}
        <div ref={bottom} />
      </div>

      {error && <div className="text-rose-400 text-sm mb-2">{error}</div>}

      <div className="flex items-end gap-2">
        <textarea
          className="input flex-1 min-h-[64px] resize-y"
          placeholder="Ask a complex, multi-source question…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }}
        />
        <div className="flex flex-col gap-2 items-end">
          <label className="flex items-center gap-1.5 text-[11px] text-slate-400 cursor-pointer select-none">
            <input type="checkbox" checked={simulate} onChange={(e) => setSimulate(e.target.checked)} />
            Simulate self-correction (demo)
          </label>
          <button className="btn-primary" onClick={submit} disabled={busy || !input.trim()}>
            {busy ? 'Running…' : 'Run task'}
          </button>
        </div>
      </div>

      {recent.length > 0 && (
        <div className="mt-4">
          <div className="text-xs text-slate-400 mb-1">Recent tasks</div>
          <div className="flex gap-2 flex-wrap">
            {recent.map((t) => (
              <Link key={t.id} to={`/trace/${t.id}`} className="badge bg-slate-800 text-slate-300 hover:bg-slate-700">
                {t.title.slice(0, 40)} · {t.status}
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
