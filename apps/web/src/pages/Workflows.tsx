import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import * as D from '@/api/laned'
import { PageHeader } from '@/components/Shell'
import { Async, Badge, Button, EmptyState, Field, Input, Modal, Notice, Panel, StatusBadge, Textarea } from '@/components/ui'
import { useAct } from '@/lib/hooks'
import { fmtDate } from '@/lib/logic'

const SAMPLE = JSON.stringify({ steps: [
  { id: 'review', type: 'approval' },
], }, null, 2)

function RunView({ id, onClose }: { id: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ['wf-run', id], queryFn: () => D.workflowRun(id), refetchInterval: 4000 })
  const cp = useQuery({ queryKey: ['wf-cp', id], queryFn: () => D.checkpoints(id), refetchInterval: 4000 })
  const act = useAct((approve: boolean) => D.approveWorkflow(id, approve), { ok: 'Decision recorded', invalidate: [['wf-run', id], ['wf-cp', id]] })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Workflow run" wide>
      <Async q={q} isEmpty={() => false}>
        {(r) => (
          <div className="space-y-3">
            <p className="flex flex-wrap items-center gap-2 text-sm"><StatusBadge status={r.status} />{r.current_step && <span>at step <span className="font-mono">{r.current_step}</span></span>}</p>
            {r.error && <Notice tone="danger">{r.error}</Notice>}
            {(r.status === 'awaiting_approval' || r.status === 'waiting_approval') && <div className="flex gap-2"><Button variant="primary" busy={act.isPending} onClick={() => act.mutate(true)}>Approve and continue</Button><Button busy={act.isPending} onClick={() => act.mutate(false)}>Reject</Button></div>}
            <h4 className="text-sm font-semibold">Checkpoints</h4>
            <Async q={cp} emptyTitle="No checkpoints yet">{(l) => <ol className="space-y-1 text-sm">{l.map((c: any) => <li key={c.id} className="rounded-md bg-sunken p-2"><span className="font-mono">{c.step}</span> <span className="text-muted">{fmtDate(c.created_at)}</span></li>)}</ol>}</Async>
          </div>
        )}
      </Async>
    </Modal>
  )
}

export default function Workflows() {
  const [name, setName] = useState('')
  const [def, setDef] = useState(SAMPLE)
  const [err, setErr] = useState('')
  const [runId, setRunId] = useState<string | null>(null)
  const list = useQuery({ queryKey: ['workflows'], queryFn: D.workflows })
  const create = useAct(() => { try { const d = JSON.parse(def); if (!Array.isArray(d.steps) || d.steps.length === 0) throw new Error('Definition needs a non-empty "steps" list.'); setErr(''); return D.createWorkflow({ name, definition: d }) } catch (e: any) { setErr(e.message); return Promise.reject(e) } }, { ok: 'Workflow saved', invalidate: [['workflows']], onDone: () => setName('') })
  const run = useAct((id: string) => D.runWorkflow(id, {}), { ok: 'Workflow started', onDone: (r) => setRunId(r.run_id ?? r.id) })
  return (
    <>
      <PageHeader title="Workflow builder" intro="Chain agent steps with approval gates. A run pauses at every approval step until you decide." />
      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="New workflow">
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate() }}>
            <Field label="Name"><Input required value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label="Definition (JSON)" hint='Steps run in order. Types: "agent" (with "agent" name and "input") and "approval". Inputs can reference "$.inputs.x" or "$.steps.id.field".'><Textarea rows={12} className="font-mono text-xs" value={def} onChange={(e) => setDef(e.target.value)} spellCheck={false} /></Field>
            {err && <p role="alert" className="text-sm text-danger">{err}</p>}
            <Button type="submit" variant="primary" busy={create.isPending}>Save workflow</Button>
          </form>
        </Panel>
        <Panel title="Saved workflows">
          <Async q={list} empty={<EmptyState title="No workflows yet">Save a definition to run it.</EmptyState>}>
            {(l) => <ul className="divide-y divide-line">{l.map((w: any) => <li key={w.id} className="flex items-center justify-between gap-2 py-2 text-sm"><div><p className="font-medium">{w.name}</p><p className="text-muted">{(w.definition?.steps ?? []).map((s: any) => s.id).join(' then ')}</p></div><div className="flex items-center gap-2">{!w.enabled && <Badge>disabled</Badge>}<Button size="sm" busy={run.isPending && run.variables === w.id} onClick={() => run.mutate(w.id)}>Run</Button></div></li>)}</ul>}
          </Async>
        </Panel>
      </div>
      {runId && <RunView id={runId} onClose={() => setRunId(null)} />}
    </>
  )
}
