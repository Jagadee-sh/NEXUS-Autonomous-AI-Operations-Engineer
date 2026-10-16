const BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1'

export type Task = {
  id: string
  title: string
  request: string
  status: string
  trace_id: string
  plan?: unknown
  result?: { answer?: string; citations?: string[]; findings?: unknown[]; corrections?: unknown[] } | null
  confidence?: number | null
  error?: string | null
  retry_count: number
  max_retries: number
  created_at: string
  started_at?: string | null
  finished_at?: string | null
}

export type Trace = {
  task_id: string
  trace_id: string
  status: string
  plan?: unknown
  retry_count: number
  confidence?: number | null
  timeline: {
    sequence: number
    agent: string
    step_type: string
    status: string
    latency_ms: number
    input: Record<string, unknown>
    output: Record<string, unknown>
    error?: string | null
    created_at?: string | null
  }[]
  validations: { passed: boolean; score: number; issues: string[]; unsupported_claims: string[] }[]
  corrections: { failure_category: string; strategy: string; description: string; succeeded: boolean }[]
  evidence: { claim: string; source_ref: string; excerpt: string; strength: number }[]
  tool_calls: { tool: string; agent: string; status: string; latency_ms: number; risk_level: string }[]
}

export type Document = {
  id: string; filename: string; content_type: string; size_bytes: number; status: string; error?: string | null; chunk_count: number; created_at: string
}
export type Dataset = {
  id: string; name: string; filename: string; status: string; error?: string | null; row_count: number; columns_json: string[]; stats_json: Record<string, unknown>; created_at: string
}
export type DataSource = { id: string; name: string; kind: string; status: string; created_at: string }
export type AgentInfo = { name: string; role: string; description: string; tools: string[]; is_active: boolean; recent_executions: number; success_rate: number | null }
export type ToolInfo = { name: string; description: string; input_schema: unknown; permission_level: string; timeout_seconds: number }
export type Approval = { id: string; task_id?: string | null; action: string; risk_level: string; payload: Record<string, unknown>; status: string; requested_by: string; reason?: string | null; created_at: string }
export type EvalDataset = { id: string; name: string; description: string; items: unknown[]; created_at: string }
export type EvalRun = { id: string; dataset_id: string; status: string; metrics: Record<string, number | string>; results: unknown[]; created_at: string }
export type Stats = {
  tasks_total: number
  tasks_by_status: Record<string, number>
  success_rate: number | null
  documents: { total: number; ready: number }
  datasets: number
  pending_approvals: number
  avg_confidence: number | null
  avg_latency_seconds: number | null
  recent_tasks: { id: string; title: string; status: string; confidence?: number | null; created_at?: string }[]
  llm_provider: string
  embedding_provider: string
  vector_store: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      msg = body?.error?.message || body?.detail || msg
    } catch { /* ignore */ }
    throw new Error(msg)
  }
  return res.json() as Promise<T>
}

export const api = {
  stats: () => request<Stats>('/stats'),
  health: () => fetch('/health').then((r) => r.json()),
  ready: () => fetch('/ready').then((r) => r.json()),
  tasks: (status?: string) => request<Task[]>(`/tasks${status ? `?status=${status}` : ''}`),
  task: (id: string) => request<Task>(`/tasks/${id}`),
  trace: (id: string) => request<Trace>(`/tasks/${id}/trace`),
  createTask: (body: { request: string; title?: string; document_ids?: string[]; dataset_ids?: string[]; datasource_id?: string }) =>
    request<Task>('/tasks', { method: 'POST', body: JSON.stringify(body) }),
  query: (body: {
    question: string
    document_ids?: string[]
    dataset_ids?: string[]
    datasource_id?: string
    wait?: boolean
    failure_injection?: { category: string; fail_first?: number } | null
  }) =>
    request<{ task_id: string; status: string; answer?: string; confidence?: number; citations?: string[]; trace_id: string }>('/query', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  documents: () => request<Document[]>('/documents'),
  uploadDocument: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return request<Document>('/documents', { method: 'POST', body: fd })
  },
  deleteDocument: (id: string) => request<{ deleted: boolean }>(`/documents/${id}`, { method: 'DELETE' }),
  datasets: () => request<Dataset[]>('/datasets'),
  uploadDataset: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return request<Dataset>('/datasets', { method: 'POST', body: fd })
  },
  datasources: () => request<DataSource[]>('/datasources'),
  createDatasource: (body: { name: string; kind: string; connection_url: string }) =>
    request<DataSource>('/datasources', { method: 'POST', body: JSON.stringify(body) }),
  testDatasource: (id: string) => request<{ ok: boolean; tables?: string[]; error?: string }>(`/datasources/${id}/test`, { method: 'POST' }),
  agents: () => request<AgentInfo[]>('/agents'),
  tools: () => request<ToolInfo[]>('/tools'),
  sandbox: () => request<Record<string, unknown>>('/tools/sandbox'),
  approvals: (status = 'pending') => request<Approval[]>(`/approvals?status=${status}`),
  approve: (id: string, reason = '') => request<Approval>(`/approvals/${id}/approve`, { method: 'POST', body: JSON.stringify({ reason }) }),
  reject: (id: string, reason = '') => request<Approval>(`/approvals/${id}/reject`, { method: 'POST', body: JSON.stringify({ reason }) }),
  evalDatasets: () => request<EvalDataset[]>('/evaluations/datasets'),
  createEvalDataset: (body: { name: string; description?: string; items: unknown[] }) =>
    request<EvalDataset>('/evaluations/datasets', { method: 'POST', body: JSON.stringify(body) }),
  evalRuns: () => request<EvalRun[]>('/evaluations/runs'),
  runEval: (dataset_id: string) => request<EvalRun>('/evaluations/run', { method: 'POST', body: JSON.stringify({ dataset_id }) }),
  startResearch: (body: { dataset_id?: string; questions?: string[]; top_k?: number }) =>
    request<EvalRun>('/evaluations/research/retrieval-comparison', { method: 'POST', body: JSON.stringify(body) }),
  latestResearch: () => request<EvalRun | null>('/evaluations/research/retrieval-comparison'),
  me: () => request<{ email: string; role: string }>('/auth/me'),
}

export const statusColor = (s: string) => {
  switch (s) {
    case 'succeeded': case 'ready': case 'approved': case 'success': case 'ok': return 'bg-emerald-500/15 text-emerald-300'
    case 'running': case 'processing': return 'bg-amber-500/15 text-amber-300'
    case 'failed': case 'rejected': case 'error': return 'bg-rose-500/15 text-rose-300'
    case 'pending': case 'queued': case 'uploaded': return 'bg-sky-500/15 text-sky-300'
    default: return 'bg-slate-500/15 text-slate-300'
  }
}
