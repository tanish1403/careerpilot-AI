import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import * as F from '@/api/lanef'
import { PageHeader } from '@/components/Shell'
import { Async, Badge, Button, EmptyState, Field, Input, Meter, Notice, Panel, Select, TabPanel, Tabs } from '@/components/ui'
import { useAct } from '@/lib/hooks'
import { fmtDate, sentence } from '@/lib/logic'

const STATUSES = ['todo', 'in_progress', 'done', 'skipped']

function PlanView({ id }: { id: string }) {
  const q = useQuery({ queryKey: ['plan', id], queryFn: () => F.studyPlan(id) })
  const inv = [['plan', id], ['plans'], ['learning-progress'], ['revisions']]
  const set = useAct((p: { id: string; status: string }) => F.patchTask(p.id, { status: p.status }), { invalidate: inv })
  const replan = useAct(() => F.replanPlan(id), { ok: 'Plan rescheduled', invalidate: inv })
  const del = useAct(() => F.deletePlan(id), { ok: 'Plan deleted', invalidate: [['plans']] })
  const exp = useAct(async () => { const t = await F.planExport(id); await navigator.clipboard?.writeText(t) }, { ok: 'Plan copied as Markdown' })
  return (
    <Async q={q} isEmpty={() => false}>
      {(p) => (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div><h3 className="font-display text-lg font-semibold">{p.name}</h3><p className="text-sm text-muted">{p.done_count} of {p.task_count} tasks done, about {p.hours_per_week} hours a week</p></div>
            <div className="flex gap-2"><Button size="sm" busy={replan.isPending} onClick={() => replan.mutate()}>Reschedule</Button><Button size="sm" onClick={() => exp.mutate()}>Copy as Markdown</Button><Button size="sm" variant="outline" onClick={() => confirm('Delete this plan?') && del.mutate()}>Delete</Button></div>
          </div>
          <Meter value={p.done_count} max={Math.max(p.task_count, 1)} label="Plan progress" />
          <ul className="divide-y divide-line">
            {p.tasks.map((t: any) => (
              <li key={t.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                <div className="min-w-0"><p className="font-medium">{t.title}</p><p className="text-muted">{t.reason}{t.hours ? ` About ${t.hours} h.` : ''} Due {fmtDate(t.due_at)}{t.revise_at ? `. Revise ${fmtDate(t.revise_at)}` : ''}</p></div>
                <Select aria-label={`Status of ${t.title}`} className="w-36" value={t.status} onChange={(e) => set.mutate({ id: t.id, status: e.target.value })}>{STATUSES.map((s) => <option key={s} value={s}>{sentence(s)}</option>)}</Select>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Async>
  )
}

export default function Learning() {
  const [sel, setSel] = useState<string | null>(null)
  const [tracks, setTracks] = useState<string[]>([])
  const [hours, setHours] = useState('6')
  const [res, setRes] = useState({ title: '', url: '', topic: '' })
  const plans = useQuery({ queryKey: ['plans'], queryFn: F.studyPlans })
  const tpl = useQuery({ queryKey: ['templates'], queryFn: F.learningTemplates })
  const gaps = useQuery({ queryKey: ['gaps'], queryFn: F.skillGaps })
  const prog = useQuery({ queryKey: ['learning-progress'], queryFn: F.learningProgress })
  const due = useQuery({ queryKey: ['revisions'], queryFn: F.revisionsDue })
  const resq = useQuery({ queryKey: ['resources'], queryFn: F.learningResources })
  const gen = useAct(() => F.generatePlan({ tracks, hours_per_week: Number(hours) }), { ok: 'Study plan created', invalidate: [['plans']], onDone: (p) => setSel(p.id) })
  const addRes = useAct(() => F.addResource({ ...res, topic: res.topic || undefined }), { ok: 'Resource added', invalidate: [['resources']], onDone: () => setRes({ title: '', url: '', topic: '' }) })
  const active = sel ?? plans.data?.[0]?.id ?? null
  return (
    <>
      <PageHeader title="Learning studio" intro="Turn skill gaps from jobs you care about into a paced study plan with spaced revision." />
      <Tabs tabs={[{ id: 'plans', label: 'Study plans' }, { id: 'gaps', label: 'Skill gaps' }, { id: 'progress', label: 'Progress' }, { id: 'resources', label: 'Resources' }]}>
        <TabPanel id="plans">
          <div className="grid gap-5 lg:grid-cols-[22rem_1fr]">
            <Panel title="Create a plan">
              <Async q={tpl} emptyTitle="No tracks available">
                {(l) => (
                  <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); gen.mutate() }}>
                    <fieldset className="space-y-1"><legend className="text-[13px] font-medium">Tracks</legend>
                      {l.map((t: any) => (
                        <label key={t.key} className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={tracks.includes(t.key)} onChange={(e) => setTracks(e.target.checked ? [...tracks, t.key] : tracks.filter((x) => x !== t.key))} /><span><span className="font-medium">{t.name}</span><br /><span className="text-muted">{t.description}</span></span></label>
                      ))}
                    </fieldset>
                    <Field label="Hours per week"><Input type="number" min="1" max="100" value={hours} onChange={(e) => setHours(e.target.value)} /></Field>
                    <Button type="submit" variant="primary" disabled={tracks.length === 0} busy={gen.isPending}>Create plan</Button>
                  </form>
                )}
              </Async>
            </Panel>
            <Panel>
              <Async q={plans} empty={<EmptyState title="No study plans yet">Pick one or more tracks and create your first plan.</EmptyState>}>
                {(l) => (
                  <div className="space-y-4">
                    {l.length > 1 && <Select aria-label="Choose plan" value={active ?? ''} onChange={(e) => setSel(e.target.value)}>{l.map((p: any) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select>}
                    {active && <PlanView id={active} />}
                  </div>
                )}
              </Async>
            </Panel>
          </div>
        </TabPanel>
        <TabPanel id="gaps">
          <Panel title="Skills your target jobs ask for that your confirmed evidence lacks">
            <Async q={gaps} emptyTitle="No skill gaps found" emptyHint="Score some jobs and confirm your profile facts to see gaps here.">
              {(l) => <ul className="divide-y divide-line">{l.map((g: any) => <li key={g.skill} className="py-2 text-sm"><span className="font-medium">{g.skill}</span> <Badge tone="warn">{g.count} jobs</Badge><p className="text-muted">{(g.jobs ?? []).map((j: any) => j.title).join(', ')}</p></li>)}</ul>}
            </Async>
          </Panel>
        </TabPanel>
        <TabPanel id="progress">
          <div className="grid gap-5 lg:grid-cols-2">
            <Panel title="Overall">
              <Async q={prog} isEmpty={() => false}>
                {(p) => (<div className="space-y-2 text-sm"><Meter value={p.overall?.percent ?? 0} label="Overall progress" /><p>{p.overall?.done} of {p.overall?.total} tasks done ({Math.round(p.overall?.percent ?? 0)} percent)</p>
                  {(p.topics ?? []).length > 0 && <ul className="space-y-1">{p.topics.map((t: any, i: number) => <li key={i} className="flex justify-between"><span>{t.topic ?? t.name}</span><span className="text-muted tabular-nums">{t.done}/{t.total}</span></li>)}</ul>}</div>)}
              </Async>
            </Panel>
            <Panel title="Revisions due">
              <Async q={due} emptyTitle="Nothing to revise today">
                {(l) => <ul className="space-y-1 text-sm">{l.map((t: any) => <li key={t.id}>{t.title} <span className="text-muted">{fmtDate(t.revise_at)}</span></li>)}</ul>}
              </Async>
            </Panel>
          </div>
        </TabPanel>
        <TabPanel id="resources">
          <div className="grid gap-5 lg:grid-cols-[1fr_22rem]">
            <Panel title="Resources">
              <Async q={resq}>
                {(l) => <ul className="divide-y divide-line">{l.map((r: any, i: number) => <li key={r.id ?? i} className="py-2 text-sm"><a className="font-medium text-brand underline" href={r.url} target="_blank" rel="noreferrer noopener">{r.title}</a> {r.topic && <Badge>{r.topic}</Badge>} <Badge tone={r.origin === 'user' ? 'brand' : 'neutral'}>{r.origin === 'user' ? 'added by you' : 'suggested'}</Badge><p className="text-xs text-muted">{r.accessed_on ? `Accessed ${r.accessed_on}` : 'Link not checked recently'}</p></li>)}</ul>}
              </Async>
            </Panel>
            <Panel title="Add a resource">
              <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); addRes.mutate() }}>
                <Field label="Title"><Input required value={res.title} onChange={(e) => setRes({ ...res, title: e.target.value })} /></Field>
                <Field label="URL"><Input required type="url" placeholder="https://" value={res.url} onChange={(e) => setRes({ ...res, url: e.target.value })} /></Field>
                <Field label="Topic"><Input value={res.topic} onChange={(e) => setRes({ ...res, topic: e.target.value })} /></Field>
                <Button type="submit" variant="primary" busy={addRes.isPending}>Add resource</Button>
              </form>
              <Notice tone="brand" className="mt-3">Suggested links are starting points. Check each one before relying on it.</Notice>
            </Panel>
          </div>
        </TabPanel>
      </Tabs>
    </>
  )
}
