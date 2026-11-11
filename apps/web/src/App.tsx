import { lazy, useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { Compass } from 'lucide-react'
import { Shell } from './components/Shell'
import { Button, ErrorState, Field, Input, Notice, Spinner } from './components/ui'
import { authStatus, login, setup } from './api/lanea'
import { setUnauthorizedHandler } from './api/client'
import { useAuth, useTheme } from './lib/store'
import { errText } from './lib/hooks'
const Overview = lazy(() => import('./pages/Overview'))
const Profile = lazy(() => import('./pages/Profile'))
const Jobs = lazy(() => import('./pages/Jobs'))
const Matching = lazy(() => import('./pages/Matching'))
const Resume = lazy(() => import('./pages/Resume'))
const Applications = lazy(() => import('./pages/Applications'))
const Planner = lazy(() => import('./pages/Planner'))
const Learning = lazy(() => import('./pages/Learning'))
const Interviews = lazy(() => import('./pages/Interviews'))
const Research = lazy(() => import('./pages/Research'))
const Agents = lazy(() => import('./pages/Agents'))
const Workflows = lazy(() => import('./pages/Workflows'))
const Integrations = lazy(() => import('./pages/Integrations'))
const Models = lazy(() => import('./pages/Models'))
const System = lazy(() => import('./pages/System'))

const qc = new QueryClient({ defaultOptions: { queries: { retry: (n, e: any) => n < 1 && ![401, 404].includes(e?.status), refetchOnWindowFocus: false } } })

export function AuthGate({ setupRequired }: { setupRequired: boolean }) {
  const setToken = useAuth((s) => s.set)
  const [u, setU] = useState('')
  const [p, setP] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setErr(''); setBusy(true)
    try {
      const r = await (setupRequired ? setup : login)(u, p)
      qc.clear(); setToken(r.token)
    } catch (x) { setErr(errText(x)) } finally { setBusy(false) }
  }
  return (
    <div className="grid min-h-full place-items-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-card border border-line bg-surface p-6" aria-labelledby="auth-title">
        <div className="flex items-center gap-2"><Compass className="h-6 w-6 text-brand" aria-hidden /><span className="font-display text-xl font-semibold">CareerPilot</span></div>
        <h1 id="auth-title" className="text-lg font-semibold">{setupRequired ? 'Create your local account' : 'Sign in'}</h1>
        {setupRequired && <Notice tone="brand">First run: this account protects the data stored on this machine. There is no password reset, so keep it safe.</Notice>}
        <Field label="Username"><Input value={u} onChange={(e) => setU(e.target.value)} autoComplete="username" required /></Field>
        <Field label="Password" hint={setupRequired ? 'Use at least 10 characters.' : undefined}>
          <Input type="password" value={p} onChange={(e) => setP(e.target.value)} autoComplete={setupRequired ? 'new-password' : 'current-password'} required />
        </Field>
        {err && <p role="alert" className="text-sm text-danger">{err}</p>}
        <Button variant="primary" type="submit" busy={busy} className="w-full">{setupRequired ? 'Create account' : 'Sign in'}</Button>
      </form>
    </div>
  )
}

function Gate() {
  const token = useAuth((s) => s.token)
  const setToken = useAuth((s) => s.set)
  useEffect(() => { setUnauthorizedHandler(() => { setToken(null); qc.clear() }); return () => setUnauthorizedHandler(null) }, [setToken])
  const st = useQuery({ queryKey: ['auth-status'], queryFn: authStatus, retry: false, staleTime: 0 })
  if (st.isLoading) return <Spinner label="Connecting" />
  if (st.error) return <div className="mx-auto max-w-lg p-6"><ErrorState error={st.error} retry={() => st.refetch()} /></div>
  if (!token) return <AuthGate setupRequired={!!st.data?.setup_required} />
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Overview />} />
        <Route path="profile" element={<Profile />} />
        <Route path="jobs" element={<Jobs />} />
        <Route path="matching" element={<Matching />} />
        <Route path="resume" element={<Resume />} />
        <Route path="applications" element={<Applications />} />
        <Route path="planner" element={<Planner />} />
        <Route path="learning" element={<Learning />} />
        <Route path="interviews" element={<Interviews />} />
        <Route path="research" element={<Research />} />
        <Route path="agents" element={<Agents />} />
        <Route path="workflows" element={<Workflows />} />
        <Route path="integrations" element={<Integrations />} />
        <Route path="models" element={<Models />} />
        <Route path="system" element={<System />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}

export default function App() {
  const theme = useTheme((s) => s.theme)
  useEffect(() => { document.documentElement.dataset.theme = theme }, [theme])
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter><Gate /></BrowserRouter>
    </QueryClientProvider>
  )
}
