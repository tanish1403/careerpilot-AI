import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import * as F from '@/api/lanef'
import * as C from '@/api/lanec'
import { PageHeader } from '@/components/Shell'
import { Async, Badge, Button, EmptyState, Field, Input, Meter, Notice, Panel, Select, Textarea } from '@/components/ui'
import { useAct } from '@/lib/hooks'
import { fmtDate, sentence } from '@/lib/logic'

const KINDS = ['technical', 'coding', 'project', 'system_design', 'behavioral']
const pct = (n?: number | null) => (n == null ? 'not assessed' : `${Math.round(n * 100)} percent`)

/** Factual correctness and communication quality are different questions, so they never share a score. */
export function FeedbackPanels({ fb }: { fb: any }) {
  const f = fb.factual_correctness ?? {}, c = fb.communication ?? {}
  return (
    <div className="grid gap-4 md:grid-cols-2" data-testid="feedback">
      <Panel title="Factual correctness">
        <div className="space-y-2 text-sm">
          <p>{f.overall == null ? <Badge tone="warn">Not assessed</Badge> : <>Rubric coverage <strong>{pct(f.overall)}</strong></>}</p>
          {f.overall != null && <Meter value={f.overall * 100} label="Factual coverage" />}
          <p className="text-muted">{f.note}</p>
          <ul className="space-y-1">{(f.per_question ?? []).map((q: any) => <li key={q.question_id} className="rounded-md bg-sunken p-2">
            <span className="font-medium">{sentence(q.topic ?? q.question_id)}</span>: {q.assessed ? pct(q.score) : 'self-review recommended'}
            {q.missing?.length > 0 && <span className="block text-muted">Not covered: {q.missing.join(', ')}</span>}</li>)}</ul>
        </div>
      </Panel>
      <Panel title="Communication">
        <div className="space-y-2 text-sm">
          <p>Overall <strong>{pct(c.overall)}</strong>, average {Math.round(c.avg_word_count ?? 0)} words per answer</p>
          {c.overall != null && <Meter value={c.overall * 100} label="Communication score" />}
          <ul className="list-disc space-y-1 pl-5">{(c.notes ?? []).map((n: string, i: number) => <li key={i}>{n}</li>)}</ul>
        </div>
      </Panel>
      <Panel title="Revision tasks" className="md:col-span-2">
        <ul className="space-y-1 text-sm">{(fb.revision_tasks ?? []).map((t: any, i: number) => <li key={i}><span className="font-medium">{sentence(t.topic)}</span>: {t.task} <span className="text-muted">{t.reason}</span></li>)}</ul>
      </Panel>
    </div>
  )
}

function Session({ id }: { id: string }) {
  const qc = useQueryClient()
  const [text, setText] = useState('')
  const list = useQuery({ queryKey: ['isessions'], queryFn: F.interviewSessions })
  const s = list.data?.find((x: any) => x.id === id)
  const [notes, setNotes] = useState<any[]>([])
  const ans = useAct(() => F.answerInterview(id, text), { onDone: (r) => { setText(''); setNotes(r.running_notes ?? []); qc.invalidateQueries({ queryKey: ['isessions'] }) } })
  const fin = useAct(() => F.finishInterview(id), { ok: 'Session finished', invalidate: [['isessions']] })
  if (!s) return null
  const last = notes[notes.length - 1]
  return (
    <div className="space-y-4">
      <Notice tone="brand">Practice questions are generic prompts from a built-in bank, not questions this company asks.</Notice>
      <ol className="space-y-2 text-sm" aria-label="Transcript">
        {s.transcript.map((t: any, i: number) => <li key={i} className={`rounded-md p-2 ${t.role === 'candidate' ? 'ml-6 bg-brand-soft' : 'bg-sunken'}`}><span className="text-xs text-muted">{t.role === 'candidate' ? 'You' : `Interviewer, ${t.label ?? 'question'}`}</span><p className="whitespace-pre-wrap">{t.text}</p></li>)}
      </ol>
      {last && <div className="rounded-md border border-line p-3 text-sm"><p className="mb-1 font-medium">Notes on your last answer</p>
        <p><span className="text-muted">Factual: </span>{last.factual?.assessed ? pct(last.factual.score) : last.factual?.note}</p>
        <p><span className="text-muted">Communication: </span>{pct(last.communication?.score)}. {(last.communication?.notes ?? []).join(' ')}</p></div>}
      {s.status === 'active' ? (
        <div className="space-y-2">
          <Field label="Your answer"><Textarea rows={5} value={text} onChange={(e) => setText(e.target.value)} /></Field>
          <div className="flex gap-2"><Button variant="primary" disabled={!text.trim()} busy={ans.isPending} onClick={() => ans.mutate()}>Submit answer</Button><Button busy={fin.isPending} onClick={() => fin.mutate()}>Finish and get feedback</Button></div>
        </div>
      ) : s.feedback ? <FeedbackPanels fb={s.feedback} /> : <p className="text-sm text-muted">Session finished.</p>}
    </div>
  )
}

export default function Interviews() {
  const [sel, setSel] = useState<string | null>(null)
  const [kind, setKind] = useState('technical')
  const [role, setRole] = useState('')
  const [jobId, setJobId] = useState('')
  const list = useQuery({ queryKey: ['isessions'], queryFn: F.interviewSessions })
  const jobs = useQuery({ queryKey: ['jobs-pick'], queryFn: () => C.jobs({ limit: 50 }) })
  const start = useAct(() => F.startInterview({ kind, target_role: role || undefined, job_id: jobId || undefined }), { ok: 'Session started', invalidate: [['isessions']], onDone: (r) => setSel(r.id) })
  return (
    <>
      <PageHeader title="Mock interview studio" intro="Practice one question at a time. Feedback on whether you were right is kept separate from feedback on how you said it." />
      <div className="grid gap-5 lg:grid-cols-[22rem_1fr]">
        <div className="space-y-5">
          <Panel title="Start a session">
            <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); start.mutate() }}>
              <Field label="Kind"><Select value={kind} onChange={(e) => setKind(e.target.value)}>{KINDS.map((k) => <option key={k} value={k}>{sentence(k)}</option>)}</Select></Field>
              <Field label="Target role (optional)"><Input value={role} onChange={(e) => setRole(e.target.value)} /></Field>
              <Field label="Based on job (optional)"><Select value={jobId} onChange={(e) => setJobId(e.target.value)}><option value="">None</option>{(jobs.data?.items ?? []).map((j) => <option key={j.id} value={j.id}>{j.title}, {j.company_name}</option>)}</Select></Field>
              <Button type="submit" variant="primary" busy={start.isPending}>Start session</Button>
            </form>
          </Panel>
          <Panel title="Past sessions">
            <Async q={list} emptyTitle="No sessions yet">
              {(l) => <ul className="space-y-1">{l.map((s: any) => <li key={s.id}><button className={`w-full rounded-md px-2 py-1.5 text-left text-sm hover:bg-sunken ${sel === s.id ? 'bg-sunken font-medium' : ''}`} onClick={() => setSel(s.id)}>{sentence(s.kind)}{s.target_role ? `, ${s.target_role}` : ''}<span className="block text-xs text-muted">{fmtDate(s.created_at)}, {s.status}</span></button></li>)}</ul>}
            </Async>
          </Panel>
        </div>
        <Panel title="Session">{sel ? <Session id={sel} key={sel} /> : <EmptyState title="No session open">Start a session or open a past one.</EmptyState>}</Panel>
      </div>
    </>
  )
}
