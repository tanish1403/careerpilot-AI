import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import * as C from '@/api/lanec'
import { PageHeader } from '@/components/Shell'
import { Async, Badge, Button, EmptyState, Field, Input, Modal, Notice, Panel, Select, StatusBadge, Switch, Table, TabPanel, Tabs } from '@/components/ui'
import { useAct } from '@/lib/hooks'
import { fmtDate, sentence } from '@/lib/logic'

function AddSource({ kinds, onClose }: { kinds: any[]; onClose: () => void }) {
  const [kind, setKind] = useState(kinds[0]?.kind ?? '')
  const [name, setName] = useState('')
  const [cfg, setCfg] = useState<Record<string, string>>({})
  const k = kinds.find((x) => x.kind === kind)
  const create = useAct(() => C.createSource({ kind, name, config: Object.fromEntries(Object.entries(cfg).filter(([, v]) => v !== '')) }), { ok: 'Source added', invalidate: [['sources']], onDone: onClose })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Add a job source">
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate() }}>
        <Field label="Kind"><Select value={kind} onChange={(e) => { setKind(e.target.value); setCfg({}) }}>{kinds.map((x) => <option key={x.kind} value={x.kind}>{x.label}</option>)}</Select></Field>
        {k && <Notice tone="brand"><strong>Permitted usage.</strong> {k.permitted_usage}</Notice>}
        <Field label="Name"><Input required value={name} onChange={(e) => setName(e.target.value)} /></Field>
        {Object.entries(k?.config_schema ?? {}).map(([key, spec]: any) => (
          <Field key={key} label={`${sentence(key)}${spec.required ? ' (required)' : ''}`}><Input required={spec.required} value={cfg[key] ?? ''} onChange={(e) => setCfg({ ...cfg, [key]: e.target.value })} /></Field>
        ))}
        <Button type="submit" variant="primary" busy={create.isPending}>Add source</Button>
      </form>
    </Modal>
  )
}

function Health({ id }: { id: string }) {
  const q = useQuery({ queryKey: ['source-health', id], queryFn: () => C.sourceHealth(id) })
  return <Async q={q} isEmpty={() => false}>{(h) => <StatusBadge status={h.status} />}</Async>
}

export default function Integrations() {
  const [adding, setAdding] = useState(false)
  const src = useQuery({ queryKey: ['sources'], queryFn: C.sources })
  const kinds = useQuery({ queryKey: ['source-kinds'], queryFn: C.sourceKinds })
  const logs = useQuery({ queryKey: ['ingestion'], queryFn: C.ingestionLogs })
  const inv = [['sources'], ['source-health'], ['ingestion'], ['jobs']]
  const toggle = useAct((p: { id: string; enabled: boolean }) => C.patchSource(p.id, { enabled: p.enabled }), { invalidate: inv })
  const test = useAct((id: string) => C.testSource(id), { ok: 'Connection test finished', invalidate: inv })
  const runIt = useAct((id: string) => C.runSource(id), { ok: 'Scan started', invalidate: inv })
  const del = useAct((id: string) => C.deleteSource(id), { ok: 'Source removed', invalidate: inv })
  return (
    <>
      <PageHeader title="Integrations" intro="Where jobs come from. Each source states what it is permitted to do; CareerPilot does not scrape logged-in sites or bypass access controls."
        actions={<Button variant="primary" onClick={() => setAdding(true)}>Add source</Button>} />
      <Tabs tabs={[{ id: 'sources', label: 'Sources' }, { id: 'kinds', label: 'Permitted usage' }, { id: 'logs', label: 'Ingestion log' }]}>
        <TabPanel id="sources">
          <Async q={src} empty={<EmptyState title="No sources yet" action={<Button onClick={() => setAdding(true)}>Add a source</Button>}>Add a public job board to start discovering jobs.</EmptyState>}>
            {(l) => (
              <Table head={['Source', 'Health', 'Last run', 'On', '']}>
                {l.map((s: any) => (
                  <tr key={s.id}>
                    <td><span className="font-medium">{s.name}</span> <Badge>{s.kind}</Badge>{s.last_error && <p className="text-xs text-danger">{s.last_error}</p>}</td>
                    <td><Health id={s.id} /></td>
                    <td>{fmtDate(s.last_run_at)}{s.last_status && <> <StatusBadge status={s.last_status} /></>}</td>
                    <td><Switch label={`Enable ${s.name}`} checked={s.enabled} onChange={(v) => toggle.mutate({ id: s.id, enabled: v })} /></td>
                    <td className="space-x-1 whitespace-nowrap"><Button size="sm" onClick={() => test.mutate(s.id)}>Test</Button><Button size="sm" onClick={() => runIt.mutate(s.id)}>Run now</Button><Button size="sm" variant="outline" onClick={() => confirm(`Remove ${s.name}?`) && del.mutate(s.id)}>Remove</Button></td>
                  </tr>))}
              </Table>
            )}
          </Async>
        </TabPanel>
        <TabPanel id="kinds">
          <Async q={kinds}>{(l) => <ul className="grid gap-3 md:grid-cols-2">{l.map((k: any) => <li key={k.kind}><Panel title={k.label}><p className="text-sm">{k.permitted_usage}</p></Panel></li>)}</ul>}</Async>
        </TabPanel>
        <TabPanel id="logs">
          <Async q={logs} emptyTitle="No ingestion runs yet">
            {(l) => <Table head={['When', 'Status', 'Fetched', 'Created', 'Detail']}>{l.map((g: any) => <tr key={g.id}><td>{fmtDate(g.started_at ?? g.created_at)}</td><td><StatusBadge status={g.status} /></td><td>{g.fetched}</td><td>{g.created}</td><td className="max-w-[40ch] truncate text-muted">{g.error ?? ''}</td></tr>)}</Table>}
          </Async>
        </TabPanel>
      </Tabs>
      {adding && kinds.data && <AddSource kinds={kinds.data} onClose={() => setAdding(false)} />}
    </>
  )
}
