import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import * as C from '@/api/lanec'
import { PageHeader } from '@/components/Shell'
import { WeightEditor } from '@/components/WeightEditor'
import { Async, Badge, Button, EmptyState, Field, Input, Meter, Notice, Panel, StatusBadge, TabPanel, Tabs, Mono } from '@/components/ui'
import { useAct } from '@/lib/hooks'
import { DISCLAIMER, sentence } from '@/lib/logic'

function Breakdown({ id }: { id: string }) {
  const q = useQuery({ queryKey: ['match', id], queryFn: () => C.match(id) })
  const [reason, setReason] = useState('')
  const fb = useAct((b: any) => C.feedback(id, b), { ok: 'Feedback saved' })
  return (
    <Async q={q} isEmpty={() => false}>
      {(m) => (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <div><p className="text-sm text-muted">Fit</p><p className="font-display text-3xl font-semibold tabular-nums">{Math.round(m.fit_score)}</p></div>
            <div><p className="text-sm text-muted">Priority</p><p className="font-display text-3xl font-semibold tabular-nums">{Math.round(m.priority_score)}</p></div>
            <div><p className="mb-1 text-sm text-muted">Eligibility</p><StatusBadge status={m.eligibility} /></div>
          </div>
          <Notice tone="brand">{m.disclaimer ? `${m.disclaimer} ` : ''}{!m.disclaimer?.toLowerCase().includes('decision-support') && DISCLAIMER}</Notice>
          <Panel title="Eligibility checks">
            <ul className="space-y-2 text-sm">
              {m.eligibility_details.map((d, i) => (
                <li key={i} className="flex flex-wrap items-start gap-2"><StatusBadge status={d.state} /><span className="min-w-0 flex-1">{d.requirement}{d.reason && <span className="block text-xs text-muted">{d.reason}</span>}{d.evidence.length > 0 && <span className="block text-xs text-muted">Evidence: {d.evidence.map((e: any) => (typeof e === 'string' ? e : e.text ?? e.fact_id ?? JSON.stringify(e))).join('; ')}</span>}</span></li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-muted">Unknown means CareerPilot could not tell. It is not a pass.</p>
          </Panel>
          <Panel title="Fit breakdown">
            <ul className="space-y-3">
              {Object.entries(m.factors).map(([k, f]) => (
                <li key={k}>
                  <div className="flex justify-between text-sm"><span>{sentence(k)} <span className="text-muted">weight {f.weight}</span>{f.insufficient_data && <Badge tone="warn" className="ml-2">limited data</Badge>}</span><span className="tabular-nums">{f.contribution.toFixed(1)} pts</span></div>
                  <Meter value={f.score} max={1} label={`${sentence(k)} score`} />
                  {f.note && <p className="mt-0.5 text-xs text-muted">{f.note}</p>}
                  {f.evidence.length > 0 && <p className="text-xs text-muted">Evidence: {f.evidence.map((e: any) => typeof e === 'string' ? e : e.text ?? e.fact_id ?? e.skill ?? JSON.stringify(e)).join('; ')}</p>}
                </li>
              ))}
            </ul>
          </Panel>
          <Panel title="Missing requirements">
            {m.missing.length === 0 ? <p className="text-sm text-muted">Nothing missing was detected.</p> : (
              <ul className="space-y-1 text-sm">{m.missing.map((x, i) => <li key={i}>{x.mandatory && <Badge tone="danger" className="mr-1">required</Badge>}<strong>{x.requirement}</strong> <span className="text-muted">{x.reason}</span></li>)}</ul>
            )}
          </Panel>
          <Panel title="Tell the matcher">
            <div className="flex flex-wrap items-end gap-2">
              <Button size="sm" onClick={() => fb.mutate({ relevant: true })}>Relevant</Button>
              <Button size="sm" onClick={() => fb.mutate({ relevant: false, reason })}>Not relevant</Button>
              <Button size="sm" onClick={() => fb.mutate({ action: 'dismiss', reason })}>Dismiss job</Button>
              <Field label="Reason (optional)" className="min-w-48 flex-1"><Input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
            </div>
          </Panel>
        </div>
      )}
    </Async>
  )
}

function Scores() {
  const q = useQuery({ queryKey: ['jobs', 'scored'], queryFn: () => C.jobs({ status: 'any', sort: 'fit', limit: 100 }) })
  const [sel, setSel] = useState<string | null>(null)
  const score = useAct(() => C.scoreAll(), { ok: 'Scoring started. Refresh in a moment.', invalidate: [['jobs']] })
  return (
    <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
      <div className="space-y-3">
        <Button variant="primary" busy={score.isPending} onClick={() => score.mutate()}>Score all jobs</Button>
        <Async q={q} isEmpty={(d) => d.items.length === 0} emptyTitle="No jobs to score" emptyHint="Import jobs in Job discovery first.">
          {(d) => (
            <ul className="space-y-1.5">
              {d.items.map((j) => (
                <li key={j.id}>
                  <button disabled={!j.match} onClick={() => j.match?.id && setSel(j.match.id)} aria-pressed={sel === j.match?.id}
                    className={`w-full rounded-md border p-2 text-left text-sm disabled:opacity-60 ${sel && sel === j.match?.id ? 'border-brand bg-brand-soft' : 'border-line bg-surface hover:bg-sunken'}`}>
                    <span className="block truncate font-medium">{j.title}</span>
                    <span className="flex items-center justify-between text-xs text-muted"><span className="truncate">{j.company_name}</span>{j.match ? <span className="tabular-nums">fit {Math.round(j.match.fit_score)} / {j.match.eligibility.replace(/_/g, ' ')}</span> : <span>not scored</span>}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Async>
      </div>
      <div>{sel ? <Breakdown id={sel} /> : <EmptyState title="Pick a scored job">See why it scored as it did, with evidence, gaps and eligibility.</EmptyState>}</div>
    </div>
  )
}

function Weights() {
  const q = useQuery({ queryKey: ['matching-config'], queryFn: C.matchingConfig })
  const save = useAct((b: any) => C.saveMatchingConfig(b), { ok: 'Weights saved. Re-score jobs to apply them.', invalidate: [['matching-config']] })
  return (
    <Async q={q} isEmpty={() => false}>
      {(c) => (
        <div className="space-y-6">
          <Panel>
            <WeightEditor key={c.version + 'f'} title="Fit weights" weights={c.weights} busy={save.isPending} onSave={(w) => save.mutate({ ...c, weights: w })} />
          </Panel>
          {c.priority_weights && <Panel><WeightEditor key={c.version + 'p'} title="Priority weights" weights={c.priority_weights} busy={save.isPending} onSave={(w) => save.mutate({ ...c, priority_weights: w })} /></Panel>}
          <p className="text-xs text-muted">Config version <Mono>{c.version}</Mono>. Changing weights creates a new version; older scores keep the version they were computed with.</p>
        </div>
      )}
    </Async>
  )
}

export default function Matching() {
  return (
    <>
      <PageHeader title="Job matching" intro="Every score is explained: what evidence supports it and what is missing." />
      <p className="mb-4 text-sm font-medium" data-testid="disclaimer">{DISCLAIMER}</p>
      <Tabs tabs={[{ id: 'scores', label: 'Scores' }, { id: 'weights', label: 'Weights' }]}>
        <TabPanel id="scores"><Scores /></TabPanel>
        <TabPanel id="weights"><Weights /></TabPanel>
      </Tabs>
    </>
  )
}
