import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Suspense, useState } from 'react'
import { Compass, UserRound, Search, Gauge, FileText, KanbanSquare, CalendarCheck, GraduationCap, Mic, Building2, Bot, Workflow, Plug, Cpu, ShieldCheck, Menu, Moon, Sun, LogOut, X } from 'lucide-react'
import { features, me } from '@/api/lanea'
import { Badge, Button, Spinner, statusTone } from './ui'
import { useAuth, useTheme, useToasts } from '@/lib/store'

export const NAV = [
  { group: 'Cockpit', items: [{ to: '/', label: 'Overview', icon: Compass, f: ['system'] }] },
  { group: 'Search', items: [
    { to: '/profile', label: 'Career evidence', icon: UserRound, f: ['profile', 'document_ingestion'] },
    { to: '/jobs', label: 'Job discovery', icon: Search, f: ['job_discovery'] },
    { to: '/matching', label: 'Job matching', icon: Gauge, f: ['matching'] },
  ] },
  { group: 'Apply', items: [
    { to: '/resume', label: 'Resume studio', icon: FileText, f: ['resume_studio'] },
    { to: '/applications', label: 'Applications', icon: KanbanSquare, f: ['applications', 'browser_autofill'] },
    { to: '/planner', label: 'Daily planner', icon: CalendarCheck, f: ['scheduler'] },
  ] },
  { group: 'Prepare', items: [
    { to: '/learning', label: 'Learning studio', icon: GraduationCap, f: ['learning'] },
    { to: '/interviews', label: 'Mock interviews', icon: Mic, f: ['interviews'] },
    { to: '/research', label: 'Company research', icon: Building2, f: ['company_research'] },
  ] },
  { group: 'Automation', items: [
    { to: '/agents', label: 'Agent control', icon: Bot, f: ['agents'] },
    { to: '/workflows', label: 'Workflows', icon: Workflow, f: ['agents'] },
    { to: '/integrations', label: 'Integrations', icon: Plug, f: ['job_discovery'] },
    { to: '/models', label: 'AI models', icon: Cpu, f: ['providers'] },
  ] },
  { group: 'System', items: [{ to: '/system', label: 'Health and data', icon: ShieldCheck, f: ['system'] }] },
]

export function useFeatures() {
  return useQuery({ queryKey: ['features'], queryFn: features, staleTime: 60_000 })
}

/** Badge for the feature(s) behind a page. Honest: shows server status verbatim. */
export function FeatureBadge({ keys }: { keys: string[] }) {
  const { data } = useFeatures()
  if (!data) return null
  return (
    <span className="flex flex-wrap gap-1">
      {keys.filter((k) => data[k]).map((k) => (
        <Badge key={k} tone={statusTone(data[k].status)} title={`${data[k].label}: ${data[k].status}`}>
          {data[k].label}: {data[k].status}
        </Badge>
      ))}
    </span>
  )
}

export function PageHeader({ title, intro, actions }: { title: string; intro?: string; actions?: React.ReactNode }) {
  const loc = useLocation()
  const item = NAV.flatMap((g) => g.items).find((i) => i.to === loc.pathname)
  return (
    <header className="mb-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold sm:text-3xl">{title}</h1>
          {intro && <p className="mt-1 max-w-[65ch] text-sm text-muted">{intro}</p>}
        </div>
        <div className="flex flex-wrap items-center gap-2">{actions}</div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">{item && <FeatureBadge keys={item.f} />}</div>
      <div className="horizon mt-3" aria-hidden />
    </header>
  )
}

function Toasts() {
  const { toasts, dismiss } = useToasts()
  return (
    <div className="fixed bottom-4 right-4 z-[60] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} role={t.kind === 'error' ? 'alert' : 'status'}
          className={`flex items-start justify-between gap-2 rounded-md border px-3 py-2 text-sm shadow-lg ${t.kind === 'error' ? 'border-danger/40 bg-danger-soft text-danger' : 'border-ok/40 bg-ok-soft text-ok'}`}>
          <span>{t.text}</span>
          <button aria-label="Dismiss" onClick={() => dismiss(t.id)}><X className="h-4 w-4" /></button>
        </div>
      ))}
    </div>
  )
}

export function Shell() {
  const [open, setOpen] = useState(false)
  const { theme, toggle } = useTheme()
  const setToken = useAuth((s) => s.set)
  const user = useQuery({ queryKey: ['me'], queryFn: me, retry: false })
  const nav = (
    <nav aria-label="Main" className="flex h-full flex-col gap-5 overflow-y-auto px-3 py-4">
      <div className="flex items-center gap-2 px-2">
        <Compass className="h-6 w-6 text-brand" aria-hidden />
        <span className="font-display text-lg font-semibold text-white">CareerPilot</span>
      </div>
      {NAV.map((g) => (
        <div key={g.group}>
          <p className="px-2 pb-1 text-xs text-rail-ink/60">{g.group}</p>
          {g.items.map((i) => (
            <NavLink key={i.to} to={i.to} end={i.to === '/'} onClick={() => setOpen(false)}
              className={({ isActive }) => `flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm ${isActive ? 'bg-white/10 text-white font-medium shadow-[inset_2px_0_0_rgb(var(--brand))]' : 'text-rail-ink hover:bg-white/5'}`}>
              <i.icon className="h-4 w-4" aria-hidden />{i.label}
            </NavLink>
          ))}
        </div>
      ))}
      <div className="mt-auto border-t border-white/10 px-2 pt-3 text-xs text-rail-ink/70">
        Local-first. You approve every submission.
      </div>
    </nav>
  )
  return (
    <div className="flex min-h-full">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 bg-rail lg:block">{nav}</aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/50" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 bg-rail">{nav}</aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="sticky top-0 z-30 flex h-12 items-center justify-between gap-2 border-b border-line bg-bg/90 px-4 backdrop-blur">
          <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open menu" onClick={() => setOpen(true)}><Menu className="h-5 w-5" /></Button>
          <span className="hidden text-sm text-muted lg:block">{user.data ? `Signed in as ${user.data.username}` : ''}</span>
          <div className="ml-auto flex items-center gap-1">
            <Button variant="ghost" size="icon" aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'} onClick={toggle}>
              {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setToken(null)}><LogOut className="h-4 w-4" />Sign out</Button>
          </div>
        </div>
        <main className="page-in mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 sm:px-6"><Suspense fallback={<Spinner />}><Outlet /></Suspense></main>
      </div>
      <Toasts />
    </div>
  )
}
