import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import * as F from '@/api/lanef'
import { PageHeader } from '@/components/Shell'
import { Async, Badge, Button, EmptyState, Field, Input, Notice, Panel, Textarea, StatusBadge } from '@/components/ui'
import { useAct } from '@/lib/hooks'
import { fmtDate } from '@/lib/logic'

export function Brief({ c }: { c: any }) {
  return (
    <div className="space-y-4" data-testid="brief">
      <div><h3 className="font-display text-xl font-semibold">{c.name}</h3>{c.role && <p className="text-sm text-muted">For the role: {c.role}</p>}</div>
      {c.note && <Notice tone="brand">{c.note}</Notice>}
      <section><h4 className="mb-1 text-sm font-semibold">Sourced facts</h4>
        {(c.claims ?? []).length === 0 ? <p className="text-sm text-muted">None. Add company URLs to fetch sourced facts.</p> : (
          <ul className="space-y-2 text-sm">{c.claims.map((cl: any, i: number) => <li key={i} className="rounded-md bg-sunken p-2"><p>{cl.text}</p><p className="break-all text-xs text-muted">{cl.source_url} (retrieved {fmtDate(cl.retrieved_at)})</p></li>)}</ul>)}
      </section>
      <section><h4 className="mb-1 text-sm font-semibold">Interview themes</h4>
        {(c.interview_themes ?? []).length === 0 ? <p className="text-sm text-muted">None added.</p> : (
          <ul className="space-y-2 text-sm">{c.interview_themes.map((t: any, i: number) => <li key={i} className="rounded-md bg-sunken p-2">
            <p>{t.theme} {t.unverified ? <Badge tone="warn">unverified</Badge> : <Badge tone="ok">sourced</Badge>}</p>
            {t.source_url ? <p className="break-all text-xs text-muted">{t.source_url} (retrieved {fmtDate(t.retrieved_at)})</p> : <p className="text-xs text-muted">{t.note}</p>}</li>)}</ul>)}
      </section>
      <section><h4 className="mb-1 text-sm font-semibold">Sources</h4>
        {(c.sources ?? []).length === 0 ? <p className="text-sm text-muted">No sources.</p> : <ul className="space-y-1 text-sm">{c.sources.map((s: any) => <li key={s.url}><span className="break-all font-mono text-xs">{s.url}</span> <span className="text-muted">retrieved {fmtDate(s.retrieved_at)}</span></li>)}</ul>}
        {(c.fetches ?? []).filter((f: any) => f.status !== 'ok').map((f: any, i: number) => <p key={i} className="mt-1 text-sm"><StatusBadge status={f.status} /> <span className="break-all font-mono text-xs">{f.url}</span> <span className="text-muted">{f.reason}</span></p>)}
      </section>
    </div>
  )
}

export default function Research() {
  const [sel, setSel] = useState<string | null>(null)
  const [f, setF] = useState({ company: '', role: '', urls: '', themes: '' })
  const list = useQuery({ queryKey: ['companies'], queryFn: F.companies })
  const run = useAct(() => F.researchCompany({
    company: f.company, role: f.role || undefined,
    urls: f.urls.split(/\s+/).filter(Boolean),
    interview_notes: f.themes.split('\n').map((l) => l.trim()).filter(Boolean).map((l) => {
      const [theme, src] = l.split(' | '); return { theme, source_url: src }
    }),
  }), { ok: 'Brief built', invalidate: [['companies']], onDone: (c) => setSel(c.id) })
  const active = sel ?? list.data?.[0]?.id
  const cur = list.data?.find((c: any) => c.id === active)
  return (
    <>
      <PageHeader title="Company research" intro="Briefs list only what a fetched page says, with its source and retrieval time. Anything without a source is labelled unverified." />
      <div className="grid gap-5 lg:grid-cols-[22rem_1fr]">
        <div className="space-y-5">
          <Panel title="Build a brief">
            <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); run.mutate() }}>
              <Field label="Company"><Input required value={f.company} onChange={(e) => setF({ ...f, company: e.target.value })} /></Field>
              <Field label="Role (optional)"><Input value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })} /></Field>
              <Field label="Company pages to read" hint="One URL per line, up to 5. robots.txt is respected."><Textarea rows={3} value={f.urls} onChange={(e) => setF({ ...f, urls: e.target.value })} /></Field>
              <Field label="Interview themes you know about" hint="One per line. Add ' | https://source' to cite a source."><Textarea rows={3} value={f.themes} onChange={(e) => setF({ ...f, themes: e.target.value })} /></Field>
              <Button type="submit" variant="primary" busy={run.isPending}>Build brief</Button>
            </form>
          </Panel>
          <Panel title="Companies">
            <Async q={list} emptyTitle="No briefs yet">
              {(l) => <ul>{l.map((c: any) => <li key={c.id}><button onClick={() => setSel(c.id)} className={`w-full rounded-md px-2 py-1.5 text-left text-sm hover:bg-sunken ${active === c.id ? 'bg-sunken font-medium' : ''}`}>{c.name}<span className="block text-xs text-muted">{c.brief_retrieved_at ? `Retrieved ${fmtDate(c.brief_retrieved_at)}` : 'No sources fetched'}</span></button></li>)}</ul>}
            </Async>
          </Panel>
        </div>
        <Panel>{cur ? <Brief c={cur} /> : <EmptyState title="No brief selected">Build a brief to see sourced facts here.</EmptyState>}</Panel>
      </div>
    </>
  )
}
