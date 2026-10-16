import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Workspace from './pages/Workspace'
import Agents from './pages/Agents'
import Knowledge from './pages/Knowledge'
import DataSources from './pages/DataSources'
import Trace from './pages/Trace'
import Evaluations from './pages/Evaluations'
import Approvals from './pages/Approvals'
import Health from './pages/Health'
import Settings from './pages/Settings'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/workspace" element={<Workspace />} />
          <Route path="/agents" element={<Agents />} />
          <Route path="/knowledge" element={<Knowledge />} />
          <Route path="/datasources" element={<DataSources />} />
          <Route path="/trace" element={<Trace />} />
          <Route path="/trace/:taskId" element={<Trace />} />
          <Route path="/evaluations" element={<Evaluations />} />
          <Route path="/approvals" element={<Approvals />} />
          <Route path="/health" element={<Health />} />
          <Route path="/settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
