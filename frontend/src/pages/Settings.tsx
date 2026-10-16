import { useEffect, useState } from 'react'
import { api, type ToolInfo } from '../lib/api'

export default function Settings() {
  const [tools, setTools] = useState<ToolInfo[]>([])
  const [sandbox, setSandbox] = useState<Record<string, unknown>>({})

  useEffect(() => {
    api.tools().then(setTools).catch(() => {})
    api.sandbox().then(setSandbox).catch(() => {})
  }, [])

  return (
    <div className="p-6 space-y-6">
      <header>
        <h1 className="text-xl font-semibold">Settings</h1>
        <p className="text-sm text-slate-400">
          Provider configuration is environment-driven (never stored in the frontend).
        </p>
      </header>

      <div className="card">
        <h2 className="text-sm font-medium text-slate-300 mb-3">Environment variables (see .env.example)</h2>
        <div className="grid md:grid-cols-2 gap-2 text-xs font-mono text-slate-400">
          {[
            'LLM_PROVIDER (local | openai | anthropic | gemini | ollama)',
            'OPENAI_API_KEY / ANTHROPIC_API_KEY / GOOGLE_API_KEY',
            'EMBEDDING_PROVIDER (local | openai | ollama)',
            'DATABASE_URL (sqlite default / postgresql production)',
            'REDIS_URL (optional; in-process queue when empty)',
            'VECTOR_STORE (memory | pgvector) + PGVECTOR_URL',
            'MAX_AGENT_ITERATIONS / MAX_RETRIES / AGENT_STEP_TIMEOUT_SECONDS',
            'SQL_TIMEOUT_SECONDS / SQL_MAX_ROWS / SANDBOX_TIMEOUT_SECONDS',
            'RATE_LIMIT_PER_MINUTE / CORS_ORIGINS / API_KEYS',
            'HTTP_TOOL_ALLOWLIST (comma-separated hostnames)',
          ].map((v) => (
            <div key={v} className="bg-slate-950 rounded px-2 py-1.5 border border-slate-800">{v}</div>
          ))}
        </div>
        <p className="text-xs text-slate-500 mt-3">
          Restart the backend after changing environment variables. Secrets never appear in API responses or frontend code.
        </p>
      </div>

      <div className="card">
        <h2 className="text-sm font-medium text-slate-300 mb-3">Python sandbox policy</h2>
        <div className="text-xs text-slate-400 space-y-1">
          <div>Isolation: <span className="text-slate-200">{String(sandbox.isolation ?? '…')}</span></div>
          <div>Timeout: <span className="text-slate-200">{String(sandbox.timeout_seconds ?? '…')}s</span> · Memory cap: <span className="text-slate-200">{String(sandbox.memory_mb ?? '…')}MB</span></div>
          <div>
            Allowed imports:{' '}
            <span className="text-cyan-300">{Array.isArray(sandbox.allowed_imports) ? (sandbox.allowed_imports as string[]).join(', ') : '…'}</span>
          </div>
          <div className="text-amber-300/80 pt-2">{String(sandbox.limitations ?? '')}</div>
        </div>
      </div>

      <div className="card">
        <h2 className="text-sm font-medium text-slate-300 mb-3">Tool catalog & permission levels</h2>
        <table className="w-full">
          <thead><tr><th className="table-th">Tool</th><th className="table-th">Risk</th><th className="table-th">Timeout</th><th className="table-th">Description</th></tr></thead>
          <tbody>
            {tools.map((t) => (
              <tr key={t.name}>
                <td className="table-td font-mono text-xs">{t.name}</td>
                <td className="table-td">
                  <span className={`badge ${t.permission_level === 'CRITICAL' || t.permission_level === 'HIGH' ? 'bg-rose-500/20 text-rose-300' : t.permission_level === 'MEDIUM' ? 'bg-amber-500/15 text-amber-300' : 'bg-emerald-500/15 text-emerald-300'}`}>
                    {t.permission_level}
                  </span>
                </td>
                <td className="table-td">{t.timeout_seconds}s</td>
                <td className="table-td text-xs text-slate-400">{t.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
