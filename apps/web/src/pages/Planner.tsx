import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import * as F from '@/api/lanef'
import { PageHeader } from '@/components/Shell'
import { Async, Badge, Button, EmptyState, Field, Input, Modal, Notice, Panel, Select, StatusBadge, Switch, Table, TabPanel, Tabs, Mono } from '@/components/ui'
import { useAct } from '@/lib/hooks'
import { fmtDate, sentence } from '@/lib/logic'

function NewTask({ kinds, onClose }: { kinds: string[]; onClose: () => void }) {
  const [f, setF] = useState({ name: '', kind: kinds[0] ?? '', cron: '0 8 * * *', timezone: 'UTC' })
  const create = useAct(() => F.createSchedulerTask({ ...f, enabled: true, config: {} }), { ok: 'Task created', invalidate: [['sched-tasks'], ['sched-status']], onDone: onClose })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="New scheduled task" description="Tasks run locally while CareerPilot is open. Cron uses five fields: minute hour day month weekday.">
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate() }}>
        <Field label="Name"><Input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Kind"><Select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{kinds.map((k) => <option key={k} value={k}>{sentence(k)}</option>)}</Select></Field>
        <Field label="Cron schedule" hint="Example: 0 8 * * 1-5 runs at 08:00 on weekdays."><Input required value={f.cron} onChange={(e) => setF({ ...f, cron: e.target.value })} className="font-mono" /></Field>
        <Field label="Time zone"><Input value={f.timezone} onChange={(e) => setF({ ...f, timezone: e.target.value })} /></Field>
        <Button type="submit" variant="primary" busy={create.isPending}>Create task</Button>
      </form>
    </Modal>
  )
}

export default function Planner() {
  const [adding, setAdding] = useState(false)
  const status = useQuery({ queryKey: ['sched-status'], queryFn: F.schedulerStatus })
  const tasks = useQuery({ queryKey: ['sched-tasks'], queryFn: F.schedulerTasks })
  const runs = useQuery({ queryKey: ['sched-runs'], queryFn: F.schedulerRuns })
  const digest = useQuery({ queryKey: ['digest'], queryFn: F.digest, retry: false })
  const weekly = useQuery({ queryKey: ['weekly'], queryFn: F.weeklyReport })
  const fu = useQuery({ queryKey: ['follow-ups'], queryFn: F.followUps })
  const inv = [['sched-tasks'], ['sched-runs'], ['sched-status']]
  const toggle = useAct((p: { id: string; enabled: boolean }) => F.patchSchedulerTask(p.id, { enabled: p.enabled }), { invalidate: inv })
  const now = useAct((id: string) => F.runTaskNow(id), { ok: 'Task ran', invalidate: [...inv, ['digest']] })
  const retry = useAct((id: string) => F.retryRun(id), { ok: 'Run retried', invalidate: inv })
  const pause = useAct((p: boolean) => (p ? F.schedulerPause() : F.schedulerResume()), { ok: 'Scheduler updated', invalidate: inv })
  return (
    <>
      <PageHeader title="Daily planner" intro="What needs attention today, plus the background tasks that keep your search moving."
        actions={<Button variant="primary" onClick={() => setAdding(true)}>New task</Button>} />
      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Today's digest">
          <Async q={digest} empty={<EmptyState title="No digest yet">Run a Daily digest task to generate one.</EmptyState>}>
            {(d) => <pre className="max-h-72 overflow-auto whitespace-pre-wrap text-sm">{typeof d === 'string' ? d : JSON.stringify(d, null, 2)}</pre>}
          </Async>
        </Panel>
        <Panel title="Follow-ups due">
          <Async q={fu} emptyTitle="Nothing due" emptyHint="Set a follow-up date on an application to see it here.">
            {(l) => <ul className="space-y-1 text-sm">{l.map((a: any) => <li key={a.id} className="flex justify-between gap-2"><span>{a.title ?? a.job?.title ?? a.id}{a.company_name ? `, ${a.company_name}` : ''}</span><span className="text-muted">{fmtDate(a.follow_up_at)}</span></li>)}</ul>}
          </Async>
        </Panel>
        <Panel title="This week">
          <Async q={weekly} isEmpty={() => false}>
            {(w) => (
              <div className="space-y-2 text-sm">
                <p className="text-muted">{fmtDate(w.period?.from)} to {fmtDate(w.period?.to)}</p>
                <ul className="grid grid-cols-2 gap-2">{Object.entries(w.activity ?? {}).map(([k, v]) => <li key={k} className="rounded-md bg-sunken p-2"><span className="block font-display text-xl font-semibold tabular-nums">{String(v)}</span><span className="text-muted">{sentence(k)}</span></li>)}</ul>
              </div>
            )}
          </Async>
        </Panel>
        <Panel title="Scheduler" action={<Async q={status} isEmpty={() => false}>{(s) => <Button size="sm" busy={pause.isPending} onClick={() => pause.mutate(!s.paused)}>{s.paused ? 'Resume scheduler' : 'Pause scheduler'}</Button>}</Async>}>
          <Async q={status} isEmpty={() => false}>
            {(s) => (
              <div className="space-y-2 text-sm">
                <p className="flex flex-wrap gap-2"><Badge tone={s.running ? 'ok' : 'danger'}>{s.running ? 'running' : 'stopped'}</Badge>{s.paused && <Badge tone="warn">paused</Badge>}<Badge>{s.tasks} tasks</Badge>{s.failed_runs > 0 && <Badge tone="danger">{s.failed_runs} failed runs</Badge>}</p>
                {!s.enabled_in_settings && <Notice>The scheduler is switched off in settings, so tasks only run when you press Run now.</Notice>}
              </div>
            )}
          </Async>
        </Panel>
      </div>
      <div className="mt-5">
        <Tabs tabs={[{ id: 'tasks', label: 'Tasks' }, { id: 'runs', label: 'Run history' }]}>
          <TabPanel id="tasks">
            <Async q={tasks} emptyTitle="No scheduled tasks" emptyHint="Create a task such as a daily digest or a job scan.">
              {(l) => (
                <Table head={['Task', 'Schedule', 'Next run', 'Last run', 'On', '']}>
                  {l.map((t: any) => (
                    <tr key={t.id}><td><span className="font-medium">{t.name}</span> <Badge>{sentence(t.kind)}</Badge></td><td><Mono>{t.cron}</Mono> <span className="text-muted">{t.timezone}</span></td><td>{fmtDate(t.next_run_at)}</td><td>{fmtDate(t.last_run_at)}</td>
                      <td><Switch label={`Enable ${t.name}`} checked={t.enabled} onChange={(v) => toggle.mutate({ id: t.id, enabled: v })} /></td>
                      <td><Button size="sm" busy={now.isPending && now.variables === t.id} onClick={() => now.mutate(t.id)}>Run now</Button></td></tr>
                  ))}
                </Table>
              )}
            </Async>
          </TabPanel>
          <TabPanel id="runs">
            <Async q={runs} emptyTitle="No runs yet">
              {(l) => (
                <Table head={['Started', 'Period', 'Status', 'Detail', '']}>
                  {l.map((r: any) => <tr key={r.id}><td>{fmtDate(r.started_at)}</td><td><Mono>{r.period_key}</Mono></td><td><StatusBadge status={r.status} /></td><td className="max-w-[40ch] truncate text-muted">{r.error ?? JSON.stringify(r.result)}</td><td>{r.status === 'failed' && <Button size="sm" onClick={() => retry.mutate(r.id)}>Retry</Button>}</td></tr>)}
                </Table>
              )}
            </Async>
          </TabPanel>
        </Tabs>
      </div>
      {adding && <NewTask kinds={status.data?.kinds ?? []} onClose={() => setAdding(false)} />}
    </>
  )
}
