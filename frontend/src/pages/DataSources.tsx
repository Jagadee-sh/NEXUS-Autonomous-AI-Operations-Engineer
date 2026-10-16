import { useEffect, useState } from 'react'
import { api, statusColor, type DataSource } from '../lib/api'

export default function DataSources() {
  const [sources, setSources] = useState<DataSource[]>([])
  const [name, setName] = useState('')
  const [kind, setKind] = useState('sqlite')
  const [url, setUrl] = useState('')
  const [msg, setMsg] = useState('')
  const [schema, setSchema] = useState<Record<string, string[]> | null>(null)

  const reload = () => { api.datasources().then(setSources).catch(() => {}) }
  useEffect(() => { reload() }, [])

  const create = async () => {
    try {
      await api.createDatasource({ name, kind, connection_url: url })
      setMsg('Data source created')
      setName(''); setUrl('')
      reload()
    } catch (e) {
      setMsg(`Failed: ${(e as Error).message}`)
    }
  }

  const test = async (id: string) => {
    const res = await api.testDatasource(id)
    setMsg(res.ok ? `OK — tables: ${(res.tables || []).join(', ')}` : `Failed: ${res.error}`)
    reload()
  }

  const showSchema = async (id: string) => {
    try {
      const res = await fetch(`/api/v1/datasources/${id}/schema`)
      const body = await res.json()
      if (!res.ok) throw new Error(body?.error?.message || res.statusText)
      setSchema(body.tables)
    } catch (e) {
      setMsg(`Schema failed: ${(e as Error).message}`)
    }
  }

  return (
    <div className="p-6 space-y-6">
      <header>
        <h1 className="text-xl font-semibold">Data Sources</h1>
        <p className="text-sm text-slate-400">Read-only SQL sources. Only SELECT queries are ever executed (AST-enforced).</p>
      </header>
      {msg && <div className="text-sm text-cyan-300">{msg}</div>}

      <div className="card grid md:grid-cols-[1fr_120px_2fr_auto] gap-3 items-end">
        <div>
          <label className="text-xs text-slate-400">Name</label>
          <input className="input mt-1" value={name} onChange={(e) => setName(e.target.value)} placeholder="Analytics DB" />
        </div>
        <div>
          <label className="text-xs text-slate-400">Kind</label>
          <select className="input mt-1" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="sqlite">sqlite</option>
            <option value="postgres">postgres</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-slate-400">Connection URL</label>
          <input className="input mt-1" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="sqlite:///./path/to.db" />
        </div>
        <button className="btn-primary" onClick={create} disabled={!name || !url}>Add</button>
      </div>

      <div className="card">
        <table className="w-full">
          <thead><tr><th className="table-th">Name</th><th className="table-th">Kind</th><th className="table-th">Status</th><th className="table-th">Actions</th></tr></thead>
          <tbody>
            {sources.map((s) => (
              <tr key={s.id}>
                <td className="table-td">{s.name}</td>
                <td className="table-td">{s.kind}</td>
                <td className="table-td"><span className={`badge ${statusColor(s.status)}`}>{s.status}</span></td>
                <td className="table-td space-x-3">
                  <button className="text-cyan-400 text-xs hover:underline" onClick={() => test(s.id)}>test</button>
                  <button className="text-cyan-400 text-xs hover:underline" onClick={() => showSchema(s.id)}>schema</button>
                </td>
              </tr>
            ))}
            {!sources.length && <tr><td className="table-td text-slate-500" colSpan={4}>No data sources configured.</td></tr>}
          </tbody>
        </table>
      </div>

      {schema && (
        <div className="card">
          <h2 className="text-sm font-medium text-slate-300 mb-2">Schema</h2>
          <div className="space-y-2 text-xs">
            {Object.entries(schema).map(([t, cols]) => (
              <div key={t}>
                <span className="text-cyan-300 font-medium">{t}</span>
                <span className="text-slate-500"> — {cols.join(', ')}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
