import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { dashboard } from '@/api/lanea'
import { PageHeader, useFeatures } from '@/components/Shell'
import { Async, Badge, Panel, StatusBadge, EmptyState } from '@/components/ui'
import { fmtDate, sentence } from '@/lib/logic'

export default function Overview() {
  const q = useQuery({ queryKey: ['dashboard'], queryFn: dashboard })
  const f = useFeatures()
  return (
    <>
      <PageHeader title="Overview" intro="Where your search stands today. Every number comes from your local data." />
      <Async q={q} isEmpty={() => false}>
        {(d) => (
          <div className="space-y-5">
            <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
              {[['Jobs tracked', d.counts?.jobs], ['New this week', d.counts?.new_jobs], ['Shortlisted', d.counts?.shortlisted], ['Applications', d.counts?.applications]].map(([k, v]) => (
                <div key={k as string} className="rounded-card border border-line bg-surface p-4">
                  <dt className="text-sm text-muted">{k}</dt>
                  <dd className="font-display text-3xl font-semibold tabular-nums">{v ?? 0}</dd>
                </div>
              ))}
            </dl>
            <div className="grid gap-5 lg:grid-cols-2">
              <Panel title="Best current matches" action={<Link className="text-sm text-brand underline" to="/matching">Open matching</Link>}>
                {(d.top_matches ?? []).length === 0 ? <EmptyState title="No scored jobs yet">Add jobs, then run scoring on the Job matching page.</EmptyState> : (
                  <ul className="divide-y divide-line">
                    {d.top_matches.map((m: any, i: number) => (
                      <li key={m.id ?? i} className="flex items-center justify-between gap-3 py-2 text-sm">
                        <span className="min-w-0 truncate">{m.title ?? m.job_id}{m.company_name ? `, ${m.company_name}` : ''}</span>
                        <Badge tone="brand">fit {Math.round(m.fit_score ?? 0)}</Badge>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>
              <Panel title="Applications by stage">
                {Object.keys(d.counts?.by_state ?? {}).length === 0 ? <EmptyState title="No applications yet">Start one from a job in Job discovery.</EmptyState> : (
                  <ul className="space-y-1 text-sm">
                    {Object.entries(d.counts.by_state).map(([k, v]) => <li key={k} className="flex justify-between"><span>{sentence(k)}</span><span className="tabular-nums">{String(v)}</span></li>)}
                  </ul>
                )}
              </Panel>
              <Panel title="Coming up">
                {(d.upcoming ?? []).length === 0 ? <p className="text-sm text-muted">No follow-ups or interviews scheduled.</p> : (
                  <ul className="space-y-1 text-sm">{d.upcoming.map((u: any, i: number) => <li key={i}>{u.title ?? u.kind ?? JSON.stringify(u)} <span className="text-muted">{fmtDate(u.at ?? u.due_at ?? u.follow_up_at)}</span></li>)}</ul>
                )}
              </Panel>
              <Panel title="Recent activity">
                {(d.recent_events ?? []).length === 0 ? <p className="text-sm text-muted">Nothing yet.</p> : (
                  <ul className="space-y-1 text-sm">{d.recent_events.slice(0, 8).map((e: any) => <li key={e.id} className="flex justify-between gap-2"><span className="font-mono text-xs">{e.action}</span><span className="text-muted">{fmtDate(e.created_at)}</span></li>)}</ul>
                )}
              </Panel>
            </div>
            <Panel title="Feature status">
              <p className="mb-2 text-sm text-muted">Shown as reported by the backend. Experimental means not yet verified by acceptance tests.</p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(f.data ?? d.feature_status ?? {}).map(([k, v]: any) => <span key={k} className="flex items-center gap-1 text-sm">{v.label ?? sentence(k)} <StatusBadge status={v.status ?? v} /></span>)}
              </div>
            </Panel>
          </div>
        )}
      </Async>
    </>
  )
}
