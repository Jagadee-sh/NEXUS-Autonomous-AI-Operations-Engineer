import { useEffect, useRef, useState } from 'react'
import { api, statusColor, type Dataset, type Document } from '../lib/api'

const DEMO_QUESTION =
  'Analyze why profitability declined in Q3. Compare Q2 and Q3, identify the top three contributing factors, verify findings using company documents, and provide three recommended actions.'

export default function Knowledge() {
  const [docs, setDocs] = useState<Document[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState('')
  const docInput = useRef<HTMLInputElement>(null)
  const dsInput = useRef<HTMLInputElement>(null)

  const reload = () => {
    api.documents().then(setDocs).catch(() => {})
    api.datasets().then(setDatasets).catch(() => {})
  }
  useEffect(reload, [])

  const uploadDoc = async (files: FileList | null) => {
    if (!files?.length) return
    setBusy('documents')
    try {
      for (const f of Array.from(files)) await api.uploadDocument(f)
      setMsg(`Uploaded ${files.length} document(s)`)
    } catch (e) {
      setMsg(`Upload failed: ${(e as Error).message}`)
    } finally {
      setBusy('')
      reload()
      if (docInput.current) docInput.current.value = ''
    }
  }

  const uploadDs = async (files: FileList | null) => {
    if (!files?.length) return
    setBusy('datasets')
    try {
      for (const f of Array.from(files)) await api.uploadDataset(f)
      setMsg(`Uploaded ${files.length} dataset(s)`)
    } catch (e) {
      setMsg(`Upload failed: ${(e as Error).message}`)
    } finally {
      setBusy('')
      reload()
      if (dsInput.current) dsInput.current.value = ''
    }
  }

  const loadDemo = async () => {
    setBusy('demo')
    setMsg('Loading demo data…')
    try {
      const res = await fetch('/api/v1/demo/load', { method: 'POST' })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(body?.error?.message || res.statusText)
      setMsg(`Demo loaded: ${body.documents ?? '?'} documents, ${body.datasets ?? '?'} datasets`)
      reload()
    } catch (e) {
      setMsg(`Demo load failed: ${(e as Error).message}. Use scripts/seed_demo_data.py instead.`)
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="p-6 space-y-6">
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold">Knowledge</h1>
          <p className="text-sm text-slate-400">Documents are extracted, chunked, embedded, and indexed for hybrid retrieval.</p>
        </div>
        <button className="btn-ghost" onClick={loadDemo} disabled={busy === 'demo'}>
          {busy === 'demo' ? 'Loading…' : 'Load demo data'}
        </button>
      </header>

      {msg && <div className="text-sm text-cyan-300">{msg}</div>}

      <div className="grid lg:grid-cols-2 gap-6">
        <section className="card">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-medium text-slate-300">Documents (PDF · DOCX · TXT · MD · CSV · XLSX)</h2>
            <button className="btn-primary" onClick={() => docInput.current?.click()} disabled={busy === 'documents'}>
              {busy === 'documents' ? 'Uploading…' : 'Upload'}
            </button>
          </div>
          <input ref={docInput} type="file" multiple accept=".pdf,.docx,.txt,.md,.csv,.xlsx" className="hidden" onChange={(e) => uploadDoc(e.target.files)} />
          <table className="w-full">
            <thead><tr><th className="table-th">File</th><th className="table-th">Status</th><th className="table-th">Chunks</th><th className="table-th"></th></tr></thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td className="table-td max-w-[220px] truncate">{d.filename}</td>
                  <td className="table-td">
                    <span className={`badge ${statusColor(d.status)}`}>{d.status}</span>
                    {d.error && <div className="text-[10px] text-rose-400 mt-1 max-w-[200px] truncate">{d.error}</div>}
                  </td>
                  <td className="table-td">{d.chunk_count}</td>
                  <td className="table-td">
                    <button className="text-rose-400 text-xs hover:underline" onClick={() => api.deleteDocument(d.id).then(reload)}>delete</button>
                  </td>
                </tr>
              ))}
              {!docs.length && <tr><td className="table-td text-slate-500" colSpan={4}>No documents yet.</td></tr>}
            </tbody>
          </table>
        </section>

        <section className="card">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-medium text-slate-300">Datasets (CSV · XLSX)</h2>
            <button className="btn-primary" onClick={() => dsInput.current?.click()} disabled={busy === 'datasets'}>
              {busy === 'datasets' ? 'Uploading…' : 'Upload'}
            </button>
          </div>
          <input ref={dsInput} type="file" multiple accept=".csv,.xlsx" className="hidden" onChange={(e) => uploadDs(e.target.files)} />
          <table className="w-full">
            <thead><tr><th className="table-th">Name</th><th className="table-th">Rows</th><th className="table-th">Status</th><th className="table-th">Columns</th></tr></thead>
            <tbody>
              {datasets.map((d) => (
                <tr key={d.id}>
                  <td className="table-td">{d.name}</td>
                  <td className="table-td">{d.row_count}</td>
                  <td className="table-td"><span className={`badge ${statusColor(d.status)}`}>{d.status}</span></td>
                  <td className="table-td text-xs text-slate-400 max-w-[260px] truncate">{d.columns_json.join(', ')}</td>
                </tr>
              ))}
              {!datasets.length && <tr><td className="table-td text-slate-500" colSpan={4}>No datasets yet.</td></tr>}
            </tbody>
          </table>
          <div className="text-xs text-slate-500 mt-4 border-t border-slate-800 pt-3">
            Suggested question after loading data: <span className="text-slate-300">{DEMO_QUESTION}</span>
          </div>
        </section>
      </div>
    </div>
  )
}
