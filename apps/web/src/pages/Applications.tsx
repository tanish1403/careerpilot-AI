import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ExternalLink } from 'lucide-react'
import * as E from '@/api/lanee'
import * as D from '@/api/laned'
import * as B from '@/api/laneb'
import { PageHeader } from '@/components/Shell'
import { KanbanBoard, MoveChoices } from '@/components/Kanban'
import { SubmitReview, type SubmitSnapshot } from '@/components/SubmitReview'
import { Async, Badge, Button, EmptyState, Field, Input, KV, Modal, Notice, Panel, Select, StatusBadge, TabPanel, Table, Tabs, Textarea } from '@/components/ui'
import { useAct } from '@/lib/hooks'
import { fmtDate, sentence } from '@/lib/logic'

function Answers({ app }: { app: E.Application }) {
  const [draft, setDraft] = useState<Record<string, string>>({})
  const inv = [['application', app.id]]
  const save = useAct(() => E.saveAnswers(app.id, app.answers.filter((a) => draft[a.id] !== undefined).map((a) => ({ id: a.id, answer: draft[a.id] }))), { ok: 'Answers saved', invalidate: inv, onDone: () => setDraft({}) })
  const confirm = useAct((id: string) => E.confirmAnswer(id), { ok: 'Answer confirmed', invalidate: inv })
  const prep = useAct(() => E.prepare(app.id), { ok: 'Preparing resume and drafting answers', invalidate: inv })
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-[60ch] text-sm text-muted">Drafts come only from facts you confirmed. Anything sensitive or unmatched is left blank for you. Editing an answer removes its evidence link and expires any pending submit approval.</p>
        <Button busy={prep.isPending} onClick={() => prep.mutate()}>Prepare resume and answers</Button>
      </div>
      {app.answers.length === 0 ? <EmptyState title="No answers yet">Run prepare to draft answers from your confirmed facts.</EmptyState> : (
        <ul className="space-y-3">
          {app.answers.map((a) => {
            const val = draft[a.id] ?? a.answer ?? ''
            return (
              <li key={a.id} className="rounded-md border border-line p-3">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <label htmlFor={`ans-${a.id}`} className="text-sm font-medium">{a.question}</label>
                  {a.sensitive && <Badge tone="danger">sensitive: never auto-filled</Badge>}
                  {a.needs_user && <Badge tone="warn">needs your answer</Badge>}
                  {a.user_confirmed ? <Badge tone="ok">confirmed</Badge> : <Badge>not confirmed</Badge>}
                  {a.evidence_ids?.length > 0 && <Badge tone="brand">{a.evidence_ids.length} evidence</Badge>}
                </div>
                <Textarea id={`ans-${a.id}`} rows={3} value={val} onChange={(e) => setDraft({ ...draft, [a.id]: e.target.value })} />
                <div className="mt-2"><Button size="sm" disabled={!a.answer || draft[a.id] !== undefined || a.user_confirmed} busy={confirm.isPending} onClick={() => confirm.mutate(a.id)}>Confirm answer</Button></div>
              </li>
            )
          })}
        </ul>
      )}
      {Object.keys(draft).length > 0 && <Button variant="primary" busy={save.isPending} onClick={() => save.mutate()}>Save edited answers</Button>}
    </div>
  )
}

function ResumePick({ app }: { app: E.Application }) {
  const rq = useQuery({ queryKey: ['resumes', app.job_id], queryFn: () => B.resumes(app.job_id) })
  const [sel, setSel] = useState(app.resume_version_id ?? '')
  const ok = useAct(() => E.approveResume(app.id, sel), { ok: 'Resume approved for this application', invalidate: [['application', app.id], ['kanban']] })
  return (
    <div className="space-y-3">
      <KV rows={[['Current resume', app.resume_version ? `Version ${app.resume_version.version_no}${app.resume_version.label ? `, ${app.resume_version.label}` : ''}` : 'None approved']]} />
      <Async q={rq} emptyTitle="No resume versions for this job" emptyHint="Generate one in Resume studio first.">
        {(list) => (
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Resume version"><Select value={sel} onChange={(e) => setSel(e.target.value)}><option value="">Choose a version</option>{list.map((r) => <option key={r.id} value={r.id}>Version {r.version_no}{r.label ? `: ${r.label}` : ''}{r.needs_confirmation_count ? ` (${r.needs_confirmation_count} to confirm)` : ''}</option>)}</Select></Field>
            <Button variant="primary" disabled={!sel} busy={ok.isPending} onClick={() => ok.mutate()}>Approve this resume</Button>
          </div>
        )}
      </Async>
    </div>
  )
}

function Review({ app }: { app: E.Application }) {
  const [ref, setRef] = useState('')
  const inv = [['application', app.id], ['kanban'], ['approvals']]
  const pend = useQuery({ queryKey: ['approvals', 'all-for', app.id], queryFn: () => D.approvals(), enabled: !!app.submit_approval })
  const req = useAct(() => E.requestSubmit(app.id), { ok: 'Review requested', invalidate: inv })
  const decide = useAct((p: { id: string; grant: boolean }) => D.decide(p.id, p.grant), { ok: 'Decision recorded', invalidate: inv })
  const done = useAct((id: string) => E.confirmSubmitted(app.id, id, ref || undefined), { ok: 'Marked as submitted', invalidate: inv })
  const ap = app.submit_approval
  const full = (pend.data ?? []).find((x: any) => x.id === ap?.id)
  const snap = (full?.snapshot ?? {}) as SubmitSnapshot
  return (
    <div className="space-y-4">
      <Notice tone="brand">CareerPilot never submits an application. Approval only unlocks the last step, which you do yourself on the employer page. Then you record that you did it.</Notice>
      {app.blockers?.length > 0 && <Notice tone="danger"><p className="font-medium">Blockers</p><ul className="list-disc pl-5">{app.blockers.map((b: any, i: number) => <li key={i}>{typeof b === 'string' ? b : b.message ?? b.reason ?? JSON.stringify(b)}</li>)}</ul></Notice>}
      {!ap || ['expired', 'denied'].includes(ap.status) ? (
        <div className="space-y-2">
          {ap && <p className="text-sm">Last approval: <StatusBadge status={ap.status} /></p>}
          <p className="text-sm text-muted">A review can be requested once the application is in User submission review, has an approved resume, and every answer is confirmed.</p>
          <Button variant="primary" busy={req.isPending} onClick={() => req.mutate()}>Request submit review</Button>
        </div>
      ) : ap.status === 'pending' ? (
        pend.isLoading ? <p className="text-sm text-muted">Loading the exact snapshot...</p> :
        <SubmitReview snapshot={{ ...snap, destination_url: snap.destination_url ?? app.destination_url }} busy={decide.isPending}
          resumeLabel={app.resume_version ? `Version ${app.resume_version.version_no}${app.resume_version.label ? `, ${app.resume_version.label}` : ''}` : undefined}
          onGrant={() => decide.mutate({ id: ap.id, grant: true })} onDeny={() => decide.mutate({ id: ap.id, grant: false })} />
      ) : ap.status === 'granted' ? (
        <div className="space-y-3">
          <p className="text-sm">Submit approval <StatusBadge status="granted" />. Open the destination, submit it yourself, then come back.</p>
          {app.destination_url && <a className="inline-flex items-center gap-1 text-sm text-brand underline" href={app.destination_url} target="_blank" rel="noreferrer noopener">Open destination <ExternalLink className="h-3.5 w-3.5" aria-hidden /></a>}
          <Field label="Confirmation reference (optional)"><Input value={ref} onChange={(e) => setRef(e.target.value)} /></Field>
          <Button variant="primary" busy={done.isPending} onClick={() => done.mutate(ap.id)}>I submitted it myself</Button>
        </div>
      ) : <p className="text-sm">Approval status: <StatusBadge status={ap.status} /></p>}
    </div>
  )
}

export function Autofill({ app }: { app: E.Application }) {
  const [sid, setSid] = useState<string | null>(null)
  const [preview, setPreview] = useState<any>(null)
  const start = useAct(() => E.startSession(app.id), { ok: 'Autofill session started', onDone: (r) => setSid(r.id ?? r.session_id) })
  const prev = useAct(() => E.fillPreview(sid!), { onDone: setPreview })
  const fill = useAct(() => E.autofill(sid!), { ok: 'Fields filled. Nothing was submitted.', invalidate: [['application', app.id]] })
  const stop = useAct(() => E.stopSession(sid!), { ok: 'Session stopped', onDone: () => { setSid(null); setPreview(null) } })
  return (
    <div className="space-y-4">
      <Notice tone="brand">Autofill opens the employer form in a controlled browser, fills fields you can see in the preview, and stops. It never clicks submit. Sensitive fields are always left for you.</Notice>
      {!sid ? (
        <div className="space-y-2">
          <p className="text-sm text-muted">The destination domain must be on your allowlist. You start every session yourself.</p>
          <Button variant="primary" busy={start.isPending} onClick={() => start.mutate()}>Start autofill session</Button>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Button busy={prev.isPending} onClick={() => prev.mutate()}>Preview fields</Button>
            <Button variant="primary" disabled={!preview} busy={fill.isPending} onClick={() => fill.mutate()}>Fill the form (no submit)</Button>
            <Button variant="outline" busy={stop.isPending} onClick={() => stop.mutate()}>Stop session</Button>
          </div>
          {preview && (
            <>
              {preview.blockers?.length > 0 && <Notice tone="warn"><ul className="list-disc pl-5">{preview.blockers.map((b: any, i: number) => <li key={i}>{typeof b === 'string' ? b : b.message ?? b.reason ?? JSON.stringify(b)}</li>)}</ul></Notice>}
              <Table head={['Field', 'Proposed value', 'Source', 'Status']}>
                {(preview.fields ?? []).map((f: any, i: number) => (
                  <tr key={i}><td>{f.label}</td><td className="max-w-[24ch] truncate">{f.status === 'sensitive' ? <em className="text-muted">left for you</em> : f.proposed_value ?? <em className="text-muted">none</em>}</td><td className="text-muted">{f.source ?? 'n/a'}</td><td><StatusBadge status={f.status} /></td></tr>
                ))}
              </Table>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function Workspace({ id, onClose }: { id: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ['application', id], queryFn: () => E.application(id) })
  const move = useAct((to: string) => E.transition(id, to), { ok: 'Application moved', invalidate: [['application', id], ['kanban']] })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Application workspace" wide>
      <Async q={q} isEmpty={() => false}>
        {(a) => (
          <div className="space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div><h3 className="font-display text-xl font-semibold">{a.job?.title ?? 'Application'}</h3><p className="text-muted">{a.job?.company_name}</p></div>
              <Badge tone="brand">{sentence(a.state)}</Badge>
            </div>
            <Tabs tabs={[{ id: 'summary', label: 'Summary' }, { id: 'answers', label: 'Answers' }, { id: 'resume', label: 'Resume' }, { id: 'review', label: 'Review and approval' }, { id: 'autofill', label: 'Autofill' }, { id: 'timeline', label: 'Timeline' }]}>
              <TabPanel id="summary">
                <div className="space-y-4">
                  <KV rows={[['Destination', <span className="break-all font-mono text-xs">{a.destination_url ?? a.job?.canonical_url ?? 'Unknown'}</span>], ['Follow up', fmtDate(a.follow_up_at)], ['Submitted', a.submitted_at ? fmtDate(a.submitted_at) : 'Not submitted'], ['Notes', a.notes ?? 'None']]} />
                  <div><h4 className="mb-1 text-sm font-semibold">Move to</h4><MoveChoices current={a.state} allowed={a.allowed_transitions} busy={move.isPending} onMove={(to) => move.mutate(to)} /></div>
                </div>
              </TabPanel>
              <TabPanel id="answers"><Answers app={a} /></TabPanel>
              <TabPanel id="resume"><ResumePick app={a} /></TabPanel>
              <TabPanel id="review"><Review app={a} /></TabPanel>
              <TabPanel id="autofill"><Autofill app={a} /></TabPanel>
              <TabPanel id="timeline">
                <ol className="space-y-2 text-sm">
                  {a.events.map((e) => <li key={e.id} className="flex flex-wrap justify-between gap-2 border-b border-line/60 pb-1"><span>{sentence(e.kind)}{e.to_state ? `: ${sentence(e.from_state ?? '')} to ${sentence(e.to_state)}` : ''} <span className="text-muted">by {e.actor}</span></span><span className="text-muted">{fmtDate(e.created_at)}</span></li>)}
                </ol>
              </TabPanel>
            </Tabs>
          </div>
        )}
      </Async>
    </Modal>
  )
}

function AllowlistPanel() {
  const q = useQuery({ queryKey: ['allowlist'], queryFn: E.allowlist })
  const ad = useQuery({ queryKey: ['adapters'], queryFn: E.adapters })
  const [text, setText] = useState<string | null>(null)
  const save = useAct(() => E.saveAllowlist((text ?? '').split(/[\s,]+/).filter(Boolean)), { ok: 'Allowlist saved', invalidate: [['allowlist']], onDone: () => setText(null) })
  return (
    <Panel title="Autofill allowlist">
      <Async q={q} isEmpty={() => false}>
        {(d) => (
          <div className="space-y-3">
            <p className="text-sm text-muted">Autofill only runs on these hostnames. A redirect to any other host stops the session.</p>
            <Textarea rows={4} aria-label="Allowed hostnames" value={text ?? d.domains.join('\n')} onChange={(e) => setText(e.target.value)} />
            <Button disabled={text === null} busy={save.isPending} onClick={() => save.mutate()}>Save allowlist</Button>
          </div>
        )}
      </Async>
      <Async q={ad}>{(l) => <ul className="mt-4 space-y-1 text-sm">{l.map((a: any) => <li key={a.name}><span className="font-medium">{a.name}</span> <span className="text-muted">{a.description}</span></li>)}</ul>}</Async>
    </Panel>
  )
}

export default function Applications() {
  const [open, setOpen] = useState<string | null>(null)
  const q = useQuery({ queryKey: ['kanban'], queryFn: E.kanban })
  return (
    <>
      <PageHeader title="Application center" intro="Track each application from discovery to offer. Moves are limited to what the server allows, and submission always needs your approval." />
      <Tabs tabs={[{ id: 'board', label: 'Board' }, { id: 'settings', label: 'Autofill settings' }]}>
        <TabPanel id="board">
          <Async q={q} isEmpty={(d) => d.columns.every((c) => c.items.length === 0)}
            empty={<EmptyState title="No applications yet">Open a job in Job discovery and choose Start application.</EmptyState>}>
            {(d) => <KanbanBoard columns={d.columns} onOpen={setOpen} />}
          </Async>
        </TabPanel>
        <TabPanel id="settings"><AllowlistPanel /></TabPanel>
      </Tabs>
      {open && <Workspace id={open} onClose={() => setOpen(null)} />}
    </>
  )
}
