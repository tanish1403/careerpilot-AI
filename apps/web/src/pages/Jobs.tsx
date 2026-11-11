import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Bookmark, BookmarkCheck, ExternalLink, Play } from 'lucide-react'
import * as C from '@/api/lanec'
import * as E from '@/api/lanee'
import { PageHeader } from '@/components/Shell'
import { Async, Badge, Button, Field, Input, KV, Modal, Notice, Panel, Select, StatusBadge, TabPanel, Tabs, Textarea, Table } from '@/components/ui'
import { useAct } from '@/lib/hooks'
import { fmtDate } from '@/lib/logic'

function JobDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const nav = useNavigate()
  const q = useQuery({ queryKey: ['job', id], queryFn: () => C.job(id) })
  const refresh = [['job', id], ['jobs']]
  const verify = useAct(() => C.verifyJob(id), { ok: 'Source link re-checked', invalidate: refresh })
  const score = useAct(() => C.scoreJobs([id]), { ok: 'Scoring started', invalidate: refresh })
  const start = useAct(() => E.createApplication(id), { ok: 'Application created', onDone: () => nav('/applications') })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Job details" wide>
      <Async q={q} isEmpty={() => false}>
        {(j) => (
          <div className="space-y-4">
            <div><h3 className="font-display text-xl font-semibold">{j.title}</h3><p className="text-muted">{j.company_name}</p></div>
            {(j.injection_flags ?? []).length > 0 && <Notice tone="danger">This posting contains text that looks like instructions to an AI. It is treated as untrusted data and ignored.</Notice>}
            <KV rows={[['Location', j.location ?? 'Not stated'], ['Work mode', j.work_mode ?? 'Not stated'], ['Salary', j.salary_text ?? 'Not stated'], ['Posted', fmtDate(j.posted_at)], ['First seen', fmtDate(j.first_seen_at)], ['Last verified', fmtDate(j.last_verified_at)], ['Status', <StatusBadge status={j.status} />],
              ['Sources', (j.sources ?? []).map((s: any) => <div key={s.url}>{s.kind}: <span className="break-all font-mono text-xs">{s.url}</span></div>)]]} />
            {(j.requirements ?? []).length > 0 && <div><h4 className="mb-1 text-sm font-semibold">Detected requirements</h4><ul className="flex flex-wrap gap-1.5">{j.requirements.map((r: any, i: number) => <Badge key={i} tone={r.mandatory ? 'brand' : 'neutral'}>{r.text ?? r.normalized ?? r.requirement ?? JSON.stringify(r)}</Badge>)}</ul></div>}
            {j.description && <details><summary className="cursor-pointer text-sm font-medium">Description (untrusted source text)</summary><pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-sunken p-3 text-xs">{j.description}</pre></details>}
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" busy={start.isPending} onClick={() => start.mutate()}>Start application</Button>
              <Button busy={score.isPending} onClick={() => score.mutate()}>Score this job</Button>
              <Button busy={verify.isPending} onClick={() => verify.mutate()}>Re-check source link</Button>
              {j.sources?.[0]?.url?.startsWith('http') && <a className="inline-flex h-9 items-center gap-1 rounded-md border border-line px-3 text-sm hover:bg-sunken" href={j.sources[0].url} target="_blank" rel="noreferrer noopener">Open original <ExternalLink className="h-3.5 w-3.5" aria-hidden /></a>}
            </div>
          </div>
        )}
      </Async>
    </Modal>
  )
}

function ImportBox() {
  const [url, setUrl] = useState('')
  const [t, setT] = useState({ title: '', company: '', description: '' })
  const byUrl = useAct(() => C.importUrl(url), { ok: 'Job imported', invalidate: [['jobs']], onDone: () => setUrl('') })
  const byText = useAct(() => C.importText(t), { ok: 'Job added', invalidate: [['jobs']], onDone: () => setT({ title: '', company: '', description: '' }) })
  const e = byUrl.error as any
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel title="Import from a link">
        <form className="space-y-2" onSubmit={(ev) => { ev.preventDefault(); if (url) byUrl.mutate() }}>
          <Field label="Job posting URL" hint="Public postings only. Login-walled pages and sites that forbid automated access are refused."><Input type="url" value={url} onChange={(x) => setUrl(x.target.value)} placeholder="https://boards.greenhouse.io/..." /></Field>
          <Button variant="primary" type="submit" busy={byUrl.isPending} disabled={!url}>Import job</Button>
          {e && <p role="alert" className="text-sm text-danger">{e.message}{e.code ? ` (${e.code})` : ''}{e.body?.apply_url && <> <a className="underline" href={e.body.apply_url} target="_blank" rel="noreferrer noopener">Open the posting yourself</a></>}</p>}
        </form>
      </Panel>
      <Panel title="Paste a job description">
        <form className="space-y-2" onSubmit={(ev) => { ev.preventDefault(); byText.mutate() }}>
          <div className="grid gap-2 sm:grid-cols-2"><Field label="Title"><Input required value={t.title} onChange={(x) => setT({ ...t, title: x.target.value })} /></Field><Field label="Company"><Input required value={t.company} onChange={(x) => setT({ ...t, company: x.target.value })} /></Field></div>
          <Field label="Description"><Textarea required rows={4} value={t.description} onChange={(x) => setT({ ...t, description: x.target.value })} /></Field>
          <Button type="submit" busy={byText.isPending}>Add job</Button>
        </form>
      </Panel>
    </div>
  )
}

function JobList() {
  const [f, setF] = useState<any>({ q: '', status: 'open', work_mode: '', source_kind: '', sort: 'priority', new_only: false, saved: false, min_fit: '' })
  const [open, setOpen] = useState<string | null>(null)
  const query = { ...f, new_only: f.new_only || undefined, saved: f.saved || undefined, limit: 50 }
  const q = useQuery({ queryKey: ['jobs', query], queryFn: () => C.jobs(query) })
  const save = useAct((j: C.JobSummary) => C.saveJob(j.id, j.saved), { invalidate: [['jobs']] })
  const set = (k: string, v: any) => setF({ ...f, [k]: v })
  return (
    <div className="space-y-4">
      <Panel>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
          <Field label="Search" className="lg:col-span-2"><Input value={f.q} onChange={(e) => set('q', e.target.value)} placeholder="Title, company or keyword" /></Field>
          <Field label="Work mode"><Select value={f.work_mode} onChange={(e) => set('work_mode', e.target.value)}><option value="">Any</option><option value="remote">Remote</option><option value="hybrid">Hybrid</option><option value="onsite">On-site</option></Select></Field>
          <Field label="Status"><Select value={f.status} onChange={(e) => set('status', e.target.value)}><option value="open">Open</option><option value="any">Any</option><option value="closed">Closed</option></Select></Field>
          <Field label="Sort by"><Select value={f.sort} onChange={(e) => set('sort', e.target.value)}><option value="priority">Priority</option><option value="fit">Fit</option><option value="posted">Posted date</option></Select></Field>
          <Field label="Minimum fit"><Input type="number" min={0} max={100} value={f.min_fit} onChange={(e) => set('min_fit', e.target.value)} /></Field>
        </div>
        <div className="mt-3 flex flex-wrap gap-4 text-sm">
          <label className="flex items-center gap-2"><input type="checkbox" checked={f.new_only} onChange={(e) => set('new_only', e.target.checked)} />New only</label>
          <label className="flex items-center gap-2"><input type="checkbox" checked={f.saved} onChange={(e) => set('saved', e.target.checked)} />Saved only</label>
        </div>
      </Panel>
      <Async q={q} isEmpty={(d) => d.items.length === 0} emptyTitle="No jobs match" emptyHint="Import a posting above, add a source in the Sources tab, or loosen the filters.">
        {(d) => (
          <>
            <p className="text-sm text-muted">{d.total} job{d.total === 1 ? '' : 's'}</p>
            <ul className="space-y-2">
              {d.items.map((j) => (
                <li key={j.id} className="flex flex-wrap items-center gap-3 rounded-card border border-line bg-surface p-3">
                  <button className="min-w-0 flex-1 text-left" onClick={() => setOpen(j.id)}>
                    <span className="block truncate font-medium">{j.title}</span>
                    <span className="block truncate text-sm text-muted">{j.company_name}{j.location ? `, ${j.location}` : ''}{j.work_mode ? ` (${j.work_mode})` : ''}</span>
                    <span className="mt-1 flex flex-wrap gap-1.5 text-xs">{j.sources.map((s) => <Badge key={s.url}>{s.kind}</Badge>)}<span className="text-muted">seen {fmtDate(j.first_seen_at)}</span></span>
                  </button>
                  {j.match ? <div className="text-right text-sm"><Badge tone="brand">fit {Math.round(j.match.fit_score)}</Badge> <Badge>priority {Math.round(j.match.priority_score)}</Badge><div className="mt-1"><StatusBadge status={j.match.eligibility} /></div></div> : <Badge>not scored</Badge>}
                  <Button variant="ghost" size="icon" aria-label={j.saved ? `Unsave ${j.title}` : `Save ${j.title}`} onClick={() => save.mutate(j)}>{j.saved ? <BookmarkCheck className="h-4 w-4 text-brand" /> : <Bookmark className="h-4 w-4" />}</Button>
                </li>
              ))}
            </ul>
          </>
        )}
      </Async>
      {open && <JobDetail id={open} onClose={() => setOpen(null)} />}
    </div>
  )
}

function Sources() {
  const q = useQuery({ queryKey: ['sources'], queryFn: C.sources })
  const kinds = useQuery({ queryKey: ['source-kinds'], queryFn: C.sourceKinds })
  const [form, setForm] = useState({ kind: '', name: '', config: '{}' })
  const inv = [['sources']]
  const create = useAct(() => C.createSource({ kind: form.kind, name: form.name, config: JSON.parse(form.config || '{}'), enabled: true }), { ok: 'Source added', invalidate: inv, onDone: () => setForm({ kind: '', name: '', config: '{}' }) })
  const run = useAct((id: string) => C.runSource(id), { ok: 'Fetch started', invalidate: [['jobs'], ['ingestion-logs']] })
  const test = useAct((id: string) => C.testSource(id), { ok: 'Source test finished' })
  const toggle = useAct((s: any) => C.patchSource(s.id, { enabled: !s.enabled }), { invalidate: inv })
  const kind = (kinds.data ?? []).find((k: any) => k.kind === form.kind)
  return (
    <div className="space-y-4">
      <Panel title="Add a source">
        <form className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); create.mutate() }}>
          <Field label="Kind"><Select required value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}><option value="">Choose...</option>{(kinds.data ?? []).map((k: any) => <option key={k.kind} value={k.kind}>{k.label ?? k.kind}</option>)}</Select></Field>
          <Field label="Name"><Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Config (JSON)" className="sm:col-span-2" hint={kind ? `Fields: ${Object.keys(kind.config_schema ?? {}).join(', ') || 'none'}` : undefined}><Textarea rows={3} className="font-mono text-xs" value={form.config} onChange={(e) => setForm({ ...form, config: e.target.value })} /></Field>
          {kind && <Notice tone="brand" className="sm:col-span-2">Permitted usage: {kind.permitted_usage}</Notice>}
          <div><Button variant="primary" type="submit" busy={create.isPending}>Add source</Button></div>
        </form>
      </Panel>
      <Async q={q} emptyTitle="No sources yet" emptyHint="Add a public job board above to pull postings automatically.">
        {(ss) => (
          <Table head={['Name', 'Kind', 'Enabled', 'Actions']}>
            {ss.map((s: any) => (
              <tr key={s.id}><td>{s.name}</td><td><Badge>{s.kind}</Badge></td><td><StatusBadge status={s.enabled ? 'open' : 'closed'} /></td>
                <td className="flex flex-wrap gap-1"><Button size="sm" busy={run.isPending} onClick={() => run.mutate(s.id)}><Play className="h-3.5 w-3.5" />Fetch now</Button><Button size="sm" onClick={() => test.mutate(s.id)}>Test</Button><Button size="sm" variant="ghost" onClick={() => toggle.mutate(s)}>{s.enabled ? 'Disable' : 'Enable'}</Button></td></tr>
            ))}
          </Table>
        )}
      </Async>
    </div>
  )
}

export default function Jobs() {
  return (
    <>
      <PageHeader title="Job discovery" intro="Postings from permitted sources, with where each came from and when it was last verified." />
      <Tabs tabs={[{ id: 'jobs', label: 'Jobs' }, { id: 'import', label: 'Import' }, { id: 'sources', label: 'Sources' }]}>
        <TabPanel id="jobs"><JobList /></TabPanel>
        <TabPanel id="import"><ImportBox /></TabPanel>
        <TabPanel id="sources"><Sources /></TabPanel>
      </Tabs>
    </>
  )
}
