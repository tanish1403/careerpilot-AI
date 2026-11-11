import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import * as A from '@/api/lanea'
import { download } from '@/api/client'
import { PageHeader, useFeatures } from '@/components/Shell'
import { Async, Badge, Button, Field, Input, KV, Modal, Notice, Panel, StatusBadge, Table, TabPanel, Tabs, Mono } from '@/components/ui'
import { useAct } from '@/lib/hooks'
import { fmtBytes, fmtDate } from '@/lib/logic'

export function ConfirmDelete({ onConfirm, onClose, busy }: { onConfirm: () => void; onClose: () => void; busy?: boolean }) {
  const [t, setT] = useState('')
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Delete all data" description="This permanently removes your profile, documents, jobs, applications and history from this machine. Export first if you may want it back.">
      <div className="space-y-3">
        <Field label='Type DELETE to confirm'><Input value={t} onChange={(e) => setT(e.target.value)} autoComplete="off" /></Field>
        <Button variant="danger" disabled={t !== 'DELETE'} busy={busy} onClick={onConfirm}>Delete everything</Button>
      </div>
    </Modal>
  )
}

function Health() {
  const q = useQuery({ queryKey: ['diag'], queryFn: A.diagnostics })
  return (
    <Async q={q} isEmpty={() => false}>
      {(d) => (
        <div className="grid gap-5 md:grid-cols-2">
          <Panel title="Service"><KV rows={[['Version', d.version], ['Python', d.python], ['Platform', d.platform], ['Database', <>{d.db?.ok ? <StatusBadge status="ok" /> : <StatusBadge status="failed" />} <span className="text-muted">{fmtBytes(d.db?.size_bytes)}, migration {d.db?.migration}</span></>], ['Free disk', fmtBytes(d.disk_free_bytes)], ['Scheduler', d.scheduler?.running ? 'running' : 'stopped']]} /></Panel>
          <Panel title="Local tools"><ul className="space-y-1 text-sm">{Object.entries(d.tools ?? {}).map(([k, v]) => <li key={k} className="flex justify-between"><span>{k}</span>{v ? <Badge tone="ok">available</Badge> : <Badge tone="warn">not found</Badge>}</li>)}</ul>
            <p className="mt-2 text-xs text-muted">Missing tools disable only the features that need them: LaTeX for PDFs, Tesseract for scanned files, Playwright for autofill, Ollama for local models.</p></Panel>
        </div>
      )}
    </Async>
  )
}

function Logs() {
  const logs = useQuery({ queryKey: ['logs'], queryFn: () => A.logs(100) })
  return (
    <Async q={logs} emptyTitle="No audit events yet">
      {(l) => <Table head={['When', 'Action', 'Actor', 'Detail']}>{l.map((e: any) => <tr key={e.id}><td className="whitespace-nowrap">{fmtDate(e.created_at)}</td><td><Mono>{e.action}</Mono></td><td>{e.actor ?? ''}</td><td className="max-w-[44ch] truncate text-muted">{JSON.stringify(e.detail)}</td></tr>)}</Table>}
    </Async>
  )
}

function Data() {
  const [del, setDel] = useState(false)
  const [rs, setRs] = useState<string | null>(null)
  const bk = useQuery({ queryKey: ['backups'], queryFn: A.backups })
  const make = useAct(() => A.backupNow(), { ok: 'Backup created', invalidate: [['backups']] })
  const restore = useAct((f: string) => A.restore(f), { ok: 'Backup restored. Reload the page.', onDone: () => setRs(null) })
  const wipe = useAct(() => A.deleteAll(), { ok: 'All data deleted', onDone: () => { setDel(false); location.reload() } })
  return (
    <div className="space-y-5">
      <Panel title="Backups" action={<Button variant="primary" busy={make.isPending} onClick={() => make.mutate()}>Back up now</Button>}>
        <Async q={bk} emptyTitle="No backups yet" emptyHint="Back up before upgrades or large imports. Backups never contain provider keys.">
          {(l) => <Table head={['File', 'Size', 'Created', '']}>{l.map((b: any) => <tr key={b.filename}><td><Mono>{b.filename}</Mono></td><td>{fmtBytes(b.size_bytes)}</td><td>{fmtDate(b.created_at)}</td><td className="space-x-1 whitespace-nowrap"><Button size="sm" onClick={() => download(`/system/backups/${b.filename}`, b.filename)}>Download</Button><Button size="sm" variant="outline" onClick={() => setRs(b.filename)}>Restore</Button></td></tr>)}</Table>}
        </Async>
      </Panel>
      <Panel title="Export your data"><p className="mb-3 text-sm text-muted">A zip of everything you own as JSON. Secrets are excluded.</p><Button onClick={() => A.exportAll()}>Export all data</Button></Panel>
      <Panel title="Delete everything" className="border-danger/40"><p className="mb-3 text-sm text-muted">Removes all data from this machine. There is no undo.</p><Button variant="danger" onClick={() => setDel(true)}>Delete all data</Button></Panel>
      {del && <ConfirmDelete busy={wipe.isPending} onConfirm={() => wipe.mutate()} onClose={() => setDel(false)} />}
      {rs && <Modal open onOpenChange={(o) => !o && setRs(null)} title="Restore backup" description="Current data will be replaced by the contents of this backup."><p className="mb-3 break-all font-mono text-sm">{rs}</p><Button variant="danger" busy={restore.isPending} onClick={() => restore.mutate(rs)}>Replace my data with this backup</Button></Modal>}
    </div>
  )
}

function FeatureTable() {
  const f = useFeatures()
  return (
    <Async q={f}>
      {(d) => (<>
        <Notice tone="brand" className="mb-3">Status is read live from the backend. Experimental means working code that has not passed its acceptance tests; nothing is claimed beyond that.</Notice>
        <Table head={['Feature', 'Status']}>{Object.entries(d).map(([k, v]) => <tr key={k}><td>{v.label} <Mono className="text-muted">{k}</Mono></td><td><StatusBadge status={v.status} /></td></tr>)}</Table>
      </>)}
    </Async>
  )
}

export default function System() {
  return (
    <>
      <PageHeader title="System health, data and security" intro="Diagnostics, backups and the exact status of every feature." />
      <Tabs tabs={[{ id: 'health', label: 'Health' }, { id: 'data', label: 'Data' }, { id: 'security', label: 'Security' }, { id: 'logs', label: 'Audit log' }, { id: 'features', label: 'Feature status' }, { id: 'docs', label: 'Docs' }]}>
        <TabPanel id="health"><Health /></TabPanel>
        <TabPanel id="data"><Data /></TabPanel>
        <TabPanel id="security">
          <Panel title="How your data is protected">
            <ul className="list-disc space-y-1.5 pl-5 text-sm">
              <li>Data stays on this machine. Nothing leaves unless you configure a remote model provider and allow it.</li>
              <li>Provider API keys are write-only. They are stored encrypted and never returned by the API or shown here.</li>
              <li>Documents and job text are treated as untrusted. Instructions inside them are ignored.</li>
              <li>Submitting an application always needs your explicit approval and your own click on the employer page.</li>
              <li>The audit log records approvals, exports and deletions with secrets redacted.</li>
              <li>Your session token lives in this tab only and is cleared when you close it.</li>
            </ul>
          </Panel>
        </TabPanel>
        <TabPanel id="logs"><Logs /></TabPanel>
        <TabPanel id="features"><FeatureTable /></TabPanel>
        <TabPanel id="docs">
          <Panel title="Where things are">
            <ul className="list-disc space-y-1.5 pl-5 text-sm">
              <li><strong>Career evidence</strong>: upload a resume, then confirm or reject each extracted fact. Only confirmed facts feed resumes and answers.</li>
              <li><strong>Job matching</strong>: scores are decision-support signals, not probabilities. Edit the weights to change what matters.</li>
              <li><strong>Resume studio</strong>: every claim links to evidence. Claims you edit need confirmation.</li>
              <li><strong>Application center</strong>: you approve the exact resume, answers and destination, then submit yourself.</li>
              <li>The full API reference is served by the backend at <Mono>/docs</Mono>.</li>
            </ul>
          </Panel>
        </TabPanel>
      </Tabs>
    </>
  )
}
