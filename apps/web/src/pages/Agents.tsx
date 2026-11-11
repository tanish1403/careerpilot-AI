import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import * as D from '@/api/laned'
import { runs as fetchRuns } from '@/api/lanea'
import { PageHeader } from '@/components/Shell'
import { SubmitReview } from '@/components/SubmitReview'
import { Async, Badge, Button, EmptyState, Field, Input, KV, Modal, Notice, Select, StatusBadge, Switch, Table, TabPanel, Tabs, Textarea } from '@/components/ui'
import { useAct } from '@/lib/hooks'
import { fmtDate, sentence } from '@/lib/logic'

function AgentDialog({ agent, onClose }: { agent: any; onClose: () => void }) {
  const models = useQuery({ queryKey: ['models'], queryFn: D.models })
  const [cfg, setCfg] = useState({ ...agent.config, fallback_model_ids: agent.config?.fallback_model_ids ?? [] })
  const [input, setInput] = useState('{}')
  const [bad, setBad] = useState('')
  const save = useAct(() => D.saveAgentConfig(agent.name, { ...cfg, budget_usd: cfg.budget_usd === '' || cfg.budget_usd == null ? null : Number(cfg.budget_usd) }), { ok: 'Agent settings saved', invalidate: [['agents']] })
  const run = useAct(() => { let v: any; try { v = JSON.parse(input) } catch { setBad('Input must be valid JSON.'); return Promise.reject(new Error('Input must be valid JSON.')) } setBad(''); return D.runAgent(agent.name, v) }, { ok: 'Run started', invalidate: [['runs']] })
  const perms = agent.permissions ?? {}
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={sentence(agent.name)} description={agent.description} wide>
      <div className="space-y-4">
        <KV rows={[['Reads', (perms.reads ?? []).join(', ') || 'nothing'], ['Writes', (perms.writes ?? []).join(', ') || 'nothing'], ['Network', perms.network ? 'yes' : 'no'], ['Browser', perms.browser ? 'yes' : 'no'], ['Can submit applications', perms.can_submit ? 'yes' : 'never']]} />
        <div className="space-y-3 border-t border-line pt-3">
          <div className="flex items-center gap-2"><Switch label="Agent enabled" checked={!!cfg.enabled} onChange={(v) => setCfg({ ...cfg, enabled: v })} /><span className="text-sm">Enabled</span></div>
          <Async q={models} emptyTitle="No models registered" emptyHint="Add a provider in AI models. Without one, agents use rules-only fallbacks.">
            {(l) => (
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Primary model"><Select value={cfg.primary_model_id ?? ''} onChange={(e) => setCfg({ ...cfg, primary_model_id: e.target.value || null })}><option value="">Automatic</option>{l.map((m: any) => <option key={m.id} value={m.id}>{m.model_id}</option>)}</Select></Field>
                <Field label="Fallback models" hint="Hold Ctrl or Cmd to pick several."><Select multiple className="h-24" value={cfg.fallback_model_ids} onChange={(e) => setCfg({ ...cfg, fallback_model_ids: Array.from(e.target.selectedOptions).map((o) => o.value) })}>{l.map((m: any) => <option key={m.id} value={m.id}>{m.model_id}</option>)}</Select></Field>
              </div>
            )}
          </Async>
          <Field label="Budget per run (USD, optional)"><Input type="number" min="0" step="0.01" value={cfg.budget_usd ?? ''} onChange={(e) => setCfg({ ...cfg, budget_usd: e.target.value })} /></Field>
          <Button variant="primary" busy={save.isPending} onClick={() => save.mutate()}>Save settings</Button>
        </div>
        <div className="space-y-2 border-t border-line pt-3">
          <Field label="Run with input (JSON)"><Textarea rows={4} className="font-mono text-xs" value={input} onChange={(e) => setInput(e.target.value)} /></Field>
          {bad && <p role="alert" className="text-sm text-danger">{bad}</p>}
          <Button busy={run.isPending} onClick={() => run.mutate()}>Run agent</Button>
        </div>
      </div>
    </Modal>
  )
}

export function ApprovalCard({ a, onDecide, busy }: { a: any; onDecide: (id: string, grant: boolean) => void; busy?: boolean }) {
  return (
    <li className="rounded-card border border-line bg-surface p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2"><Badge tone="brand">{sentence(a.kind)}</Badge><StatusBadge status={a.status} /><span className="text-xs text-muted">{fmtDate(a.created_at)}</span></div>
      {a.kind === 'submit'
        ? <SubmitReview snapshot={a.snapshot} busy={busy} onGrant={() => onDecide(a.id, true)} onDeny={() => onDecide(a.id, false)} />
        : (<>
          <pre className="max-h-48 overflow-auto rounded-md bg-sunken p-2 text-xs">{JSON.stringify(a.snapshot, null, 2)}</pre>
          <div className="mt-2 flex gap-2"><Button variant="primary" size="sm" busy={busy} onClick={() => onDecide(a.id, true)}>Approve</Button><Button size="sm" busy={busy} onClick={() => onDecide(a.id, false)}>Deny</Button></div>
        </>)}
    </li>
  )
}

export default function Agents() {
  const [open, setOpen] = useState<any>(null)
  const agents = useQuery({ queryKey: ['agents'], queryFn: D.agents })
  const runs = useQuery({ queryKey: ['runs'], queryFn: () => fetchRuns({ limit: 50 }), refetchInterval: 5000 })
  const appr = useQuery({ queryKey: ['approvals', 'pending'], queryFn: () => D.approvals('pending') })
  const ctl = useAct((p: { id: string; a: 'pause' | 'resume' | 'cancel' }) => D.runControl(p.id, p.a), { ok: 'Run updated', invalidate: [['runs']] })
  const decide = useAct((p: { id: string; grant: boolean }) => D.decide(p.id, p.grant), { ok: 'Decision recorded', invalidate: [['approvals'], ['application']] })
  return (
    <>
      <PageHeader title="Agent control center" intro="Agents propose; you decide. Each agent lists exactly what it may read and write, and none of them can submit an application." />
      <Tabs tabs={[{ id: 'agents', label: 'Agents' }, { id: 'runs', label: 'Runs' }, { id: 'approvals', label: `Approvals inbox${appr.data?.length ? ` (${appr.data.length})` : ''}` }]}>
        <TabPanel id="agents">
          <Async q={agents} emptyTitle="No agents registered">
            {(l) => <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{l.map((a: any) => (
              <li key={a.name} className="rounded-card border border-line bg-surface p-4">
                <div className="flex items-start justify-between gap-2"><h3 className="font-display font-semibold">{sentence(a.name)}</h3><Badge tone={a.config?.enabled ? 'ok' : 'neutral'}>{a.config?.enabled ? 'enabled' : 'disabled'}</Badge></div>
                <p className="mt-1 text-sm text-muted">{a.description}</p>
                <div className="mt-2 flex flex-wrap gap-1">{a.permissions?.network && <Badge tone="warn">network</Badge>}{a.permissions?.browser && <Badge tone="warn">browser</Badge>}<Badge tone="ok">cannot submit</Badge></div>
                <Button size="sm" className="mt-3" onClick={() => setOpen(a)}>Configure and run</Button>
              </li>))}</ul>}
          </Async>
        </TabPanel>
        <TabPanel id="runs">
          <Async q={runs} emptyTitle="No runs yet" emptyHint="Runs from agents, scoring, workflows and source scans appear here.">
            {(l) => (
              <Table head={['Agent', 'Status', 'Started', 'Detail', '']}>
                {l.map((r: any) => <tr key={r.id}><td>{r.agent ?? 'n/a'}</td><td><StatusBadge status={r.status} /></td><td>{fmtDate(r.started_at)}</td><td className="max-w-[36ch] truncate text-muted">{r.error ?? ''}</td>
                  <td className="space-x-1 whitespace-nowrap">
                    {r.status === 'running' && <Button size="sm" onClick={() => ctl.mutate({ id: r.id, a: 'pause' })}>Pause</Button>}
                    {r.status === 'paused' && <Button size="sm" onClick={() => ctl.mutate({ id: r.id, a: 'resume' })}>Resume</Button>}
                    {['running', 'paused', 'pending'].includes(r.status) && <Button size="sm" variant="outline" onClick={() => ctl.mutate({ id: r.id, a: 'cancel' })}>Cancel</Button>}
                  </td></tr>)}
              </Table>
            )}
          </Async>
        </TabPanel>
        <TabPanel id="approvals">
          <Notice tone="brand" className="mb-3">Approvals are decisions only you can make. Granting a submit approval never submits anything.</Notice>
          <Async q={appr} empty={<EmptyState title="Nothing waiting for you">Pending approvals from applications and workflows land here.</EmptyState>}>
            {(l) => <ul className="space-y-3">{l.map((a: any) => <ApprovalCard key={a.id} a={a} busy={decide.isPending} onDecide={(id, grant) => decide.mutate({ id, grant })} />)}</ul>}
          </Async>
        </TabPanel>
      </Tabs>
      {open && <AgentDialog agent={open} onClose={() => setOpen(null)} />}
    </>
  )
}
