import { useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Pencil, Upload, X } from 'lucide-react'
import * as B from '@/api/laneb'
import { PageHeader } from '@/components/Shell'
import { Async, Badge, Button, Field, Input, Meter, Modal, Notice, Panel, StatusBadge, TabPanel, Tabs, Textarea, Mono } from '@/components/ui'
import { useAct } from '@/lib/hooks'
import { factText, fmtDate, sentence } from '@/lib/logic'

function FactRow({ f }: { f: B.Fact }) {
  const [edit, setEdit] = useState(false)
  const isObj = typeof f.value === 'object' && f.value !== null
  const [text, setText] = useState(isObj ? JSON.stringify(f.value, null, 2) : String(f.value ?? ''))
  const inv = [['facts']]
  const confirm = useAct(() => B.confirmFact(f.id), { ok: 'Fact confirmed', invalidate: inv })
  const reject = useAct(() => B.rejectFact(f.id), { ok: 'Fact rejected', invalidate: inv })
  const save = useAct((c: boolean) => {
    let v: any = text
    if (isObj) v = JSON.parse(text)
    return B.editFact(f.id, v, c)
  }, { ok: 'Fact updated', invalidate: inv, onDone: () => setEdit(false) })
  const proposed = f.status === 'proposed'
  return (
    <li className={`rounded-md border p-3 ${proposed ? 'border-warn/50 bg-warn-soft/40' : 'border-line bg-surface'}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge>{sentence(f.category)}</Badge>
            <StatusBadge status={f.status} />
            {proposed && <Badge tone="warn">Not verified: will not be used until you confirm</Badge>}
            {f.confidence != null && <span className="text-xs text-muted">extraction confidence {Math.round(f.confidence * 100)}%</span>}
          </div>
          <p className="mt-1.5 break-words text-sm">{factText(f.value) || <em className="text-muted">empty</em>}</p>
          {f.source_document_id && <p className="mt-1 text-xs text-muted">Source document <Mono>{f.source_document_id.slice(0, 8)}</Mono></p>}
        </div>
        <div className="flex gap-1">
          {f.status !== 'confirmed' && <Button size="sm" variant="primary" busy={confirm.isPending} onClick={() => confirm.mutate()}><Check className="h-4 w-4" />Confirm</Button>}
          {f.status !== 'rejected' && <Button size="sm" busy={reject.isPending} onClick={() => reject.mutate()}><X className="h-4 w-4" />Reject</Button>}
          <Button size="sm" variant="ghost" aria-label="Edit fact" onClick={() => setEdit(true)}><Pencil className="h-4 w-4" />Edit</Button>
        </div>
      </div>
      <Modal open={edit} onOpenChange={setEdit} title="Edit fact" description="Saving an edit marks the fact as proposed until you confirm it, unless you choose Save and confirm.">
        <Textarea rows={isObj ? 10 : 4} value={text} onChange={(e) => setText(e.target.value)} className={isObj ? 'font-mono text-xs' : ''} aria-label="Fact value" />
        <div className="mt-3 flex gap-2">
          <Button busy={save.isPending} onClick={() => save.mutate(false)}>Save as proposed</Button>
          <Button variant="primary" busy={save.isPending} onClick={() => save.mutate(true)}>Save and confirm</Button>
        </div>
      </Modal>
    </li>
  )
}

function Facts() {
  const [status, setStatus] = useState('proposed')
  const q = useQuery({ queryKey: ['facts', status], queryFn: () => B.facts({ status: status === 'all' ? undefined : status }) })
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filter facts by status">
        {['proposed', 'confirmed', 'rejected', 'all'].map((s) => <Button key={s} size="sm" variant={status === s ? 'primary' : 'outline'} aria-pressed={status === s} onClick={() => setStatus(s)}>{sentence(s)}</Button>)}
      </div>
      <Async q={q} emptyTitle={`No ${status === 'all' ? '' : status + ' '}facts`} emptyHint="Upload a resume in the Documents tab and CareerPilot will propose facts for you to review.">
        {(fs) => <ul className="space-y-2">{fs.map((f) => <FactRow key={f.id} f={f} />)}</ul>}
      </Async>
    </div>
  )
}

function Documents() {
  const qc = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const q = useQuery({ queryKey: ['documents'], queryFn: B.documents })
  const up = useAct((f: File) => B.uploadDocument(f), { ok: 'Uploaded. Review the proposed facts next.', onDone: () => { qc.invalidateQueries({ queryKey: ['documents'] }); qc.invalidateQueries({ queryKey: ['facts'] }) } })
  return (
    <div className="space-y-4">
      <Panel title="Upload a document">
        <p className="mb-3 text-sm text-muted">PDF, DOCX, TXT, Markdown, RTF, LaTeX or HTML. Extracted facts are proposals only; nothing reaches your resumes until you confirm it.</p>
        <input ref={input} type="file" className="sr-only" aria-label="Choose a document" accept=".pdf,.docx,.doc,.txt,.md,.rtf,.tex,.html,.htm,.png,.jpg,.jpeg" onChange={(e) => { const f = e.target.files?.[0]; if (f) up.mutate(f); e.target.value = '' }} />
        <Button variant="primary" busy={up.isPending} onClick={() => input.current?.click()}><Upload className="h-4 w-4" />Choose file</Button>
        {up.error && <p role="alert" className="mt-2 text-sm text-danger">{(up.error as any).message}</p>}
      </Panel>
      <Async q={q} emptyTitle="No documents uploaded" emptyHint="Your uploaded resumes appear here.">
        {(ds) => (
          <ul className="divide-y divide-line rounded-card border border-line bg-surface">
            {ds.map((d: any) => <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 p-3 text-sm"><span>{d.filename ?? d.name ?? d.id}</span><span className="text-muted">{d.kind} {fmtDate(d.created_at)}</span></li>)}
          </ul>
        )}
      </Async>
    </div>
  )
}

function Details() {
  const q = useQuery({ queryKey: ['profile'], queryFn: B.profile })
  const [form, setForm] = useState<any>(null)
  const act = useAct((b: any) => B.saveProfile(b), { ok: 'Profile saved', invalidate: [['profile']] })
  return (
    <Async q={q} isEmpty={() => false}>
      {(p) => {
        const v = form ?? p
        const set = (k: string, val: string) => setForm({ ...v, [k]: val })
        return (
          <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
            <Panel title="Basics">
              <div className="grid gap-3 sm:grid-cols-2">
                {[['full_name', 'Full name'], ['headline', 'Headline'], ['email', 'Email'], ['phone', 'Phone'], ['location', 'Location']].map(([k, l]) => (
                  <Field key={k} label={l}><Input value={v[k] ?? ''} onChange={(e) => set(k, e.target.value)} /></Field>
                ))}
                <Field label="Summary" className="sm:col-span-2"><Textarea rows={4} value={v.summary ?? ''} onChange={(e) => set('summary', e.target.value)} /></Field>
              </div>
              <Button variant="primary" className="mt-3" busy={act.isPending} onClick={() => act.mutate({ full_name: v.full_name, headline: v.headline, email: v.email, phone: v.phone, location: v.location, summary: v.summary, links: v.links, preferences: v.preferences })}>Save profile</Button>
            </Panel>
            <div className="space-y-4">
              <Panel title="Completeness">
                <p className="mb-1 text-sm tabular-nums">{Math.round(p.completeness?.score ?? 0)}%</p>
                <Meter value={p.completeness?.score ?? 0} label="Profile completeness" />
                {(p.completeness?.missing ?? []).length > 0 && <ul className="mt-3 list-disc space-y-0.5 pl-4 text-sm text-muted">{p.completeness.missing.map((m: string) => <li key={m}>{m}</li>)}</ul>}
              </Panel>
              {(p.contradictions ?? []).length > 0 && (
                <Panel title="Contradictions to resolve">
                  <ul className="space-y-1 text-sm">{p.contradictions.map((c: any, i: number) => <li key={i}><Badge tone="warn">{c.kind}</Badge> {c.detail}</li>)}</ul>
                </Panel>
              )}
            </div>
          </div>
        )
      }}
    </Async>
  )
}

export default function Profile() {
  return (
    <>
      <PageHeader title="Career evidence" intro="Facts about you that resumes and applications may use. Only confirmed facts count as evidence." />
      <Notice tone="warn" className="mb-4">Facts extracted from documents are <strong>proposed, not verified</strong>. Confirm, edit or reject each one.</Notice>
      <Tabs tabs={[{ id: 'facts', label: 'Review facts' }, { id: 'docs', label: 'Documents' }, { id: 'profile', label: 'Profile details' }]}>
        <TabPanel id="facts"><Facts /></TabPanel>
        <TabPanel id="docs"><Documents /></TabPanel>
        <TabPanel id="profile"><Details /></TabPanel>
      </Tabs>
    </>
  )
}
