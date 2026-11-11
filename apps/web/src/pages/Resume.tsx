import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import * as B from '@/api/laneb'
import * as C from '@/api/lanec'
import { PageHeader } from '@/components/Shell'
import { Async, Badge, Button, EmptyState, ErrorState, Field, Input, Modal, Notice, Select, Spinner, StatusBadge, TabPanel, Tabs, Textarea, Mono } from '@/components/ui'
import { useAct } from '@/lib/hooks'
import { fmtDate } from '@/lib/logic'

function Generate({ onDone }: { onDone: (id: string) => void }) {
  const [open, setOpen] = useState(false)
  const jobs = useQuery({ queryKey: ['jobs', 'pick'], queryFn: () => C.jobs({ status: 'any', limit: 100 }), enabled: open })
  const tpl = useQuery({ queryKey: ['templates'], queryFn: B.templates, enabled: open })
  const [f, setF] = useState({ job_id: '', template_id: '', label: '', job_description: '' })
  const gen = useAct(() => B.generateResume({ job_id: f.job_id || undefined, template_id: f.template_id || undefined, label: f.label || undefined, job_description: f.job_description || undefined }), {
    ok: 'Resume version created', invalidate: [['resumes']], onDone: (r) => { setOpen(false); onDone(r.id) },
  })
  const err = gen.error as any
  return (
    <>
      <Button variant="primary" onClick={() => setOpen(true)}>Generate resume</Button>
      <Modal open={open} onOpenChange={setOpen} title="Generate a resume" description="Built only from facts you have confirmed. Anything the system cannot trace to evidence is flagged for you.">
        <div className="space-y-3">
          <Field label="Tailor to job"><Select value={f.job_id} onChange={(e) => setF({ ...f, job_id: e.target.value })}><option value="">General (no job)</option>{(jobs.data?.items ?? []).map((j) => <option key={j.id} value={j.id}>{j.title}, {j.company_name}</option>)}</Select></Field>
          {!f.job_id && <Field label="Or paste a job description"><Textarea rows={3} value={f.job_description} onChange={(e) => setF({ ...f, job_description: e.target.value })} /></Field>}
          <Field label="Template"><Select value={f.template_id} onChange={(e) => setF({ ...f, template_id: e.target.value })}><option value="">Default</option>{(tpl.data ?? []).map((t: any) => <option key={t.id} value={t.id}>{t.name}{t.ats_friendly ? ' (ATS friendly)' : ''}</option>)}</Select></Field>
          <Field label="Label (optional)"><Input value={f.label} onChange={(e) => setF({ ...f, label: e.target.value })} /></Field>
          {err && <p role="alert" className="text-sm text-danger">{err.message}{err.code === 'no_confirmed_facts' && ' Confirm some facts in Career evidence first.'}</p>}
          <Button variant="primary" busy={gen.isPending} onClick={() => gen.mutate()}>Generate</Button>
        </div>
      </Modal>
    </>
  )
}

function Preview({ id, hasPdf }: { id: string; hasPdf: boolean }) {
  const [url, setUrl] = useState<string | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let dead = false, u: string | null = null
    setUrl(null); setErr(null)
    if (hasPdf) B.pdfUrl(id).then((x) => { if (dead) URL.revokeObjectURL(x); else { u = x; setUrl(x) } }).catch((e) => !dead && setErr(e))
    return () => { dead = true; if (u) URL.revokeObjectURL(u) }
  }, [id, hasPdf, tick])
  const compile = useAct(() => B.compile(id), { ok: 'Compiled', invalidate: [['resume', id], ['resumes']], onDone: () => setTick((t) => t + 1) })
  return (
    <div className="space-y-2">
      <Button busy={compile.isPending} onClick={() => compile.mutate()}>{hasPdf ? 'Recompile PDF' : 'Compile PDF'}</Button>
      {err != null && <ErrorState error={err} />}
      {!hasPdf ? <EmptyState title="No PDF yet">Compile the LaTeX source to preview it here.</EmptyState> : url ? <iframe title="Resume PDF preview" src={url} className="h-[70vh] w-full rounded-md border border-line bg-white" /> : <Spinner />}
    </div>
  )
}

function Claims({ v }: { v: B.ResumeVersion }) {
  const confirm = useAct((c: string) => B.confirmClaim(v.id, c), { ok: 'Claim confirmed', invalidate: [['resume', v.id], ['resumes']] })
  const claims = v.claims ?? []
  const pending = claims.filter((c) => c.needs_confirmation).length
  return (
    <div className="space-y-3">
      <Notice tone={pending ? 'warn' : 'brand'}>{pending ? `${pending} claim${pending > 1 ? 's' : ''} need your confirmation before this resume should be sent. They are not backed by confirmed evidence.` : 'Every claim traces to confirmed evidence.'}</Notice>
      {claims.length === 0 ? <EmptyState title="No claims recorded" /> : (
        <ul className="space-y-2">
          {claims.map((c) => (
            <li key={c.id} className={`rounded-md border p-3 text-sm ${c.needs_confirmation ? 'border-warn/60 bg-warn-soft/40' : 'border-line bg-surface'}`}>
              <p>{c.text}</p>
              <div className="mt-1.5 flex flex-wrap items-center gap-2">
                {c.needs_confirmation ? <Badge tone="warn">Needs confirmation</Badge> : <Badge tone="ok">Evidence-backed</Badge>}
                <span className="text-xs text-muted">{c.evidence_ids.length} evidence item{c.evidence_ids.length === 1 ? '' : 's'}</span>
                {c.evidence_ids.slice(0, 3).map((e) => <Mono key={e} className="text-muted">{e.slice(0, 8)}</Mono>)}
                {c.needs_confirmation && <Button size="sm" variant="primary" className="ml-auto" busy={confirm.isPending} onClick={() => confirm.mutate(c.id)}>I confirm this is true</Button>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Diff({ v, all }: { v: B.ResumeVersion; all: B.ResumeVersion[] }) {
  const [against, setAgainst] = useState('original')
  const q = useQuery({ queryKey: ['diff', v.id, against], queryFn: () => B.diff(v.id, against) })
  return (
    <div className="space-y-3">
      <Field label="Compare with"><Select value={against} onChange={(e) => setAgainst(e.target.value)}><option value="original">Original generated version</option>{all.filter((x) => x.id !== v.id).map((x) => <option key={x.id} value={x.id}>Version {x.version_no}{x.label ? `: ${x.label}` : ''}</option>)}</Select></Field>
      <Async q={q} isEmpty={(d) => !(d.hunks ?? []).length} emptyTitle="No differences">
        {(d) => (
          <>
            {d.summary && <p className="text-sm text-muted">{typeof d.summary === 'string' ? d.summary : Object.entries(d.summary).map(([k, x]) => `${k}: ${x}`).join(', ')}</p>}
            <pre className="max-h-[60vh] overflow-auto rounded-md border border-line bg-sunken p-3 font-mono text-xs leading-5">
              {d.hunks.map((h: any, i: number) => <span key={i} className={`block whitespace-pre-wrap ${h.op === 'insert' || h.op === 'add' ? 'bg-ok-soft text-ok' : h.op === 'delete' || h.op === 'remove' ? 'bg-danger-soft text-danger' : h.op === 'replace' ? 'bg-warn-soft text-warn' : 'text-muted'}`}>{({ insert: '+ ', add: '+ ', delete: '- ', remove: '- ', replace: '~ ' } as any)[h.op] ?? '  '}{h.text}</span>)}
            </pre>
          </>
        )}
      </Async>
    </div>
  )
}

function CoverLetter({ v }: { v: B.ResumeVersion }) {
  const jobs = useQuery({ queryKey: ['jobs', 'pick'], queryFn: () => C.jobs({ status: 'any', limit: 100 }) })
  const [job, setJob] = useState(v.job_id ?? '')
  const gen = useAct(() => B.coverLetter({ job_id: job, resume_id: v.id }), { ok: 'Cover letter drafted' })
  const r = gen.data
  return (
    <div className="space-y-3">
      <Field label="Job"><Select value={job} onChange={(e) => setJob(e.target.value)}><option value="">Choose a job...</option>{(jobs.data?.items ?? []).map((j) => <option key={j.id} value={j.id}>{j.title}, {j.company_name}</option>)}</Select></Field>
      <Button variant="primary" disabled={!job} busy={gen.isPending} onClick={() => gen.mutate()}>Draft cover letter</Button>
      {gen.error != null && <p role="alert" className="text-sm text-danger">{(gen.error as any).message}</p>}
      {r && (
        <>
          {(r.needs_confirmation ?? []).length > 0 && <Notice>{r.needs_confirmation.length} statement(s) are not backed by confirmed evidence. Check them before using this letter.</Notice>}
          <Textarea rows={14} readOnly value={r.text} aria-label="Cover letter draft" />
          <p className="text-xs text-muted">Drafts are not saved. Copy the text if you want to keep it.</p>
        </>
      )}
    </div>
  )
}

function Editor({ id, all, onOpen }: { id: string; all: B.ResumeVersion[]; onOpen: (id: string) => void }) {
  const q = useQuery({ queryKey: ['resume', id], queryFn: () => B.resume(id) })
  const [src, setSrc] = useState<string | null>(null)
  useEffect(() => setSrc(null), [id])
  const save = useAct((s: string) => B.saveSource(id, s), { ok: 'Saved as a new version', invalidate: [['resumes']], onDone: (r) => onOpen(r.id) })
  const restore = useAct(() => B.restoreResume(id), { ok: 'Restored as a new version', invalidate: [['resumes']], onDone: (r) => onOpen(r.id) })
  const saveErr = save.error as any
  return (
    <Async q={q} isEmpty={() => false}>
      {(v) => {
        const text = src ?? v.latex_source ?? ''
        const rep = v.validation_report ?? {}
        return (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="font-display text-lg font-semibold">Version {v.version_no}{v.label ? `: ${v.label}` : ''}</h2>
              {v.stale && <Badge tone="warn">profile changed since</Badge>}
              <Button size="sm" className="ml-auto" busy={restore.isPending} onClick={() => restore.mutate()}>Restore this version</Button>
            </div>
            {rep && Object.keys(rep).length > 0 && <details className="text-sm"><summary className="cursor-pointer">Validation report</summary><pre className="mt-1 max-h-40 overflow-auto rounded-md bg-sunken p-2 text-xs">{JSON.stringify(rep, null, 2)}</pre></details>}
            <Tabs tabs={[{ id: 'src', label: 'LaTeX source' }, { id: 'pdf', label: 'PDF preview' }, { id: 'claims', label: `Claims${v.needs_confirmation_count ? ` (${v.needs_confirmation_count} to confirm)` : ''}` }, { id: 'diff', label: 'Diff' }, { id: 'cover', label: 'Cover letter' }]}>
              <TabPanel id="src">
                <Textarea rows={22} spellCheck={false} className="font-mono text-xs leading-5" aria-label="LaTeX source" value={text} onChange={(e) => setSrc(e.target.value)} />
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <Button variant="primary" disabled={src === null || src === v.latex_source} busy={save.isPending} onClick={() => save.mutate(text)}>Save as new version</Button>
                  <span className="text-xs text-muted">Edited lines become claims that need your confirmation.</span>
                </div>
                {saveErr && <p role="alert" className="mt-2 text-sm text-danger">{saveErr.message}{saveErr.code === 'unsafe_latex' && ' (blocked: the source uses commands that are not allowed)'}</p>}
              </TabPanel>
              <TabPanel id="pdf"><Preview id={id} hasPdf={v.pdf_available} /></TabPanel>
              <TabPanel id="claims"><Claims v={v} /></TabPanel>
              <TabPanel id="diff"><Diff v={v} all={all} /></TabPanel>
              <TabPanel id="cover"><CoverLetter v={v} /></TabPanel>
            </Tabs>
          </div>
        )
      }}
    </Async>
  )
}

export default function Resume() {
  const q = useQuery({ queryKey: ['resumes'], queryFn: () => B.resumes() })
  const [sel, setSel] = useState<string | null>(null)
  const active = sel ?? q.data?.[0]?.id ?? null
  return (
    <>
      <PageHeader title="Resume studio" intro="Every resume version is LaTeX you can read and edit. Nothing is added that is not backed by confirmed evidence." actions={<Generate onDone={setSel} />} />
      <div className="grid gap-4 lg:grid-cols-[17rem_1fr]">
        <Async q={q} emptyTitle="No resumes yet" emptyHint="Confirm facts in Career evidence, then generate your first version.">
          {(vs) => (
            <ul className="space-y-1.5" aria-label="Resume versions">
              {vs.map((v) => (
                <li key={v.id}>
                  <button onClick={() => setSel(v.id)} aria-pressed={active === v.id} className={`w-full rounded-md border p-2.5 text-left text-sm ${active === v.id ? 'border-brand bg-brand-soft' : 'border-line bg-surface hover:bg-sunken'}`}>
                    <span className="flex items-center justify-between font-medium">Version {v.version_no}{v.needs_confirmation_count > 0 && <Badge tone="warn">{v.needs_confirmation_count} to confirm</Badge>}</span>
                    <span className="block truncate text-muted">{v.label ?? 'Untitled'}</span>
                    <span className="flex items-center justify-between text-xs text-muted">{fmtDate(v.created_at)}<StatusBadge status={v.pdf_available ? 'ok' : 'pending'} /></span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Async>
        <div className="min-w-0">{active && q.data ? <Editor key={active} id={active} all={q.data} onOpen={setSel} /> : !q.isLoading && !q.error && <EmptyState title="Select or generate a version" />}</div>
      </div>
    </>
  )
}
