import { NavLink, Outlet } from 'react-router-dom'
import { useEffect, useState } from 'react'

const NAV = [
  { to: '/', label: 'Dashboard', icon: '◧' },
  { to: '/workspace', label: 'AI Workspace', icon: '✦' },
  { to: '/agents', label: 'Agents', icon: '⬡' },
  { to: '/knowledge', label: 'Knowledge', icon: '▣' },
  { to: '/datasources', label: 'Data Sources', icon: '⌬' },
  { to: '/trace', label: 'Task Trace', icon: '⇉' },
  { to: '/evaluations', label: 'Evaluations', icon: '◑' },
  { to: '/approvals', label: 'Approvals', icon: '✓' },
  { to: '/health', label: 'System Health', icon: '♥' },
  { to: '/settings', label: 'Settings', icon: '⚙' },
]

export default function Layout() {
  const [pending, setPending] = useState(0)
  useEffect(() => {
    const load = () => {
      fetch(`${import.meta.env.VITE_API_BASE_URL || '/api/v1'}/approvals?status=pending`)
        .then((r) => (r.ok ? r.json() : []))
        .then((rows) => setPending(Array.isArray(rows) ? rows.length : 0))
        .catch(() => setPending(0))
    }
    load()
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [])

  return (
    <div className="flex min-h-screen">
      <aside className="w-60 shrink-0 border-r border-slate-800 bg-slate-950 flex flex-col">
        <div className="px-4 py-5 border-b border-slate-800">
          <div className="text-lg font-bold tracking-tight text-cyan-400">NEXUS</div>
          <div className="text-[11px] text-slate-500">Enterprise Intelligence Fabric</div>
        </div>
        <nav className="flex-1 p-2 space-y-0.5 overflow-y-auto">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === '/'}
              className={({ isActive }) =>
                `flex items-center justify-between px-3 py-2 rounded-lg text-sm transition ${
                  isActive ? 'bg-cyan-600/15 text-cyan-300' : 'text-slate-300 hover:bg-slate-900'
                }`
              }
            >
              <span>
                <span className="mr-2 text-slate-500">{n.icon}</span>
                {n.label}
              </span>
              {n.to === '/approvals' && pending > 0 && (
                <span className="badge bg-amber-500/20 text-amber-300">{pending}</span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="p-3 text-[10px] text-slate-600 border-t border-slate-800">
          NEXUS MVP · local-first
        </div>
      </aside>
      <main className="flex-1 overflow-x-hidden">
        <Outlet />
      </main>
    </div>
  )
}
