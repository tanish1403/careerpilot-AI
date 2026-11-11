import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import * as D from '@/api/laned'
import { PageHeader } from '@/components/Shell'
import { Async, Badge, Button, EmptyState, Field, Input, KV, Modal, Notice, Panel, SecretInput, Select, StatusBadge, Switch, Table, TabPanel, Tabs } from '@/components/ui'
import { useAct } from '@/lib/hooks'
import { fmtDate } from '@/lib/logic'

const CAPS = ['json_mode', 'tool_calling', 'vision', 'long_context', 'embeddings']

export function ProviderForm({ initial, presets, onClose }: { initial?: D.Provider; presets: any[]; onClose: () => void }) {
  const [f, setF] = useState({ display_name: initial?.display_name ?? '', protocol: initial?.protocol ?? 'openai_compatible', base_url: initial?.base_url ?? '', timeout_s: initial?.timeout_s ?? 60, max_retries: initial?.max_retries ?? 2, enabled: initial?.enabled ?? true })
  const [key, setKey] = useState('')
  const save = useAct(() => {
    const body: any = { ...f }
    if (key) body.api_key = key
    return initial ? D.patchProvider(initial.id, body) : D.createProvider(body)
  }, { ok: 'Provider saved', invalidate: [['providers']], onDone: () => { setKey(''); onClose() } })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={initial ? `Edit ${initial.display_name}` : 'Add a provider'} description="Presets are suggested defaults only. Check the base URL with your provider.">
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
        {!initial && (
          <Field label="Start from a preset"><Select defaultValue="" onChange={(e) => { const p = presets.find((x) => x.id === e.target.value); if (p) setF({ ...f, display_name: p.name, protocol: p.protocol, base_url: p.base_url }) }}><option value="">Custom</option>{presets.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select></Field>
        )}
        <Field label="Display name"><Input required value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.target.value })} /></Field>
        <Field label="Protocol"><Select value={f.protocol} onChange={(e) => setF({ ...f, protocol: e.target.value })}><option value="openai_compatible">OpenAI compatible</option><option value="ollama">Ollama</option><option value="anthropic">Anthropic</option></Select></Field>
        <Field label="Base URL"><Input required value={f.base_url} onChange={(e) => setF({ ...f, base_url: e.target.value })} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Timeout (seconds)"><Input type="number" min="1" max="600" value={f.timeout_s} onChange={(e) => setF({ ...f, timeout_s: Number(e.target.value) })} /></Field>
          <Field label="Max retries"><Input type="number" min="0" max="10" value={f.max_retries} onChange={(e) => setF({ ...f, max_retries: Number(e.target.value) })} /></Field>
        </div>
        <SecretInput hasSecret={!!initial?.has_secret} value={key} onChange={setKey} />
        <Button type="submit" variant="primary" busy={save.isPending}>Save provider</Button>
      </form>
    </Modal>
  )
}

function ModelRow({ m, name }: { m: any; name?: string }) {
  const patch = useAct((b: any) => D.patchModel(m.id, b), { invalidate: [['models']] })
  const caps = m.capabilities ?? {}
  return (
    <tr>
      <td><span className="font-medium">{m.model_id}</span><p className="text-xs text-muted">{name}</p></td>
      <td><div className="flex flex-wrap gap-x-3 gap-y-1">{CAPS.map((c) => <label key={c} className="flex items-center gap-1 text-xs"><input type="checkbox" checked={!!caps[c]} onChange={(e) => patch.mutate({ capabilities: { ...caps, [c]: e.target.checked } })} />{c.replace('_', ' ')}</label>)}</div></td>
      <td><label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={m.verified} onChange={(e) => patch.mutate({ verified: e.target.checked })} />verified by me</label></td>
      <td><Switch label={`Enable ${m.model_id}`} checked={m.enabled} onChange={(v) => patch.mutate({ enabled: v })} /></td>
    </tr>
  )
}

export default function Models() {
  const [edit, setEdit] = useState<D.Provider | 'new' | null>(null)
  const [result, setResult] = useState<Record<string, string>>({})
  const prov = useQuery({ queryKey: ['providers'], queryFn: D.providers })
  const pre = useQuery({ queryKey: ['presets'], queryFn: D.presets })
  const mod = useQuery({ queryKey: ['models'], queryFn: D.models })
  const use = useQuery({ queryKey: ['usage'], queryFn: D.usage })
  const test = useAct((id: string) => D.testProvider(id).then((r) => { setResult((x) => ({ ...x, [id]: r.ok ? `Reachable, ${r.latency_ms} ms` : `Failed: ${r.detail}` })); return r }), { invalidate: [['providers']] })
  const disc = useAct((id: string) => D.discover(id), { ok: 'Model discovery finished', invalidate: [['models']] })
  const del = useAct((id: string) => D.deleteProvider(id), { ok: 'Provider removed', invalidate: [['providers'], ['models']] })
  const names = Object.fromEntries((prov.data ?? []).map((p) => [p.id, p.display_name]))
  return (
    <>
      <PageHeader title="AI model manager" intro="Connect model providers. Routing uses the capabilities you declare or verify here, never guesses from a model name. Sensitive documents stay on local providers unless you allow otherwise."
        actions={<Button variant="primary" onClick={() => setEdit('new')}>Add provider</Button>} />
      <Tabs tabs={[{ id: 'providers', label: 'Providers' }, { id: 'models', label: 'Models and capabilities' }, { id: 'usage', label: 'Usage' }]}>
        <TabPanel id="providers">
          <Async q={prov} empty={<EmptyState title="No providers yet" action={<Button onClick={() => setEdit('new')}>Add a provider</Button>}>Without a provider, agents use rules-only fallbacks. Local Ollama works without a key.</EmptyState>}>
            {(l) => <ul className="grid gap-3 md:grid-cols-2">{l.map((p) => (
              <li key={p.id} className="rounded-card border border-line bg-surface p-4">
                <div className="flex items-start justify-between gap-2"><h3 className="font-display font-semibold">{p.display_name}</h3><div className="flex gap-1">{p.local && <Badge tone="ok">local</Badge>}{p.has_secret && <Badge tone="ok">secret set</Badge>}{!p.enabled && <Badge>disabled</Badge>}</div></div>
                <KV rows={[['Protocol', p.protocol], ['URL', <span className="break-all font-mono text-xs">{p.base_url}</span>], ['Last test', p.last_test_at ? <>{fmtDate(p.last_test_at)} <StatusBadge status={p.last_test_ok ? 'ok' : 'failed'} /></> : 'Never tested']]} />
                {result[p.id] && <p role="status" className="mt-2 text-sm">{result[p.id]}</p>}
                <div className="mt-3 flex flex-wrap gap-2"><Button size="sm" busy={test.isPending && test.variables === p.id} onClick={() => test.mutate(p.id)}>Test</Button><Button size="sm" busy={disc.isPending && disc.variables === p.id} onClick={() => disc.mutate(p.id)}>Discover models</Button><Button size="sm" onClick={() => setEdit(p)}>Edit</Button><Button size="sm" variant="outline" onClick={() => confirm(`Remove ${p.display_name}?`) && del.mutate(p.id)}>Remove</Button></div>
              </li>))}</ul>}
          </Async>
        </TabPanel>
        <TabPanel id="models">
          <Async q={mod} emptyTitle="No models registered" emptyHint="Use Discover models on a provider to list what it offers.">
            {(l) => <><Notice tone="brand" className="mb-3">Discovered capabilities are claims by the provider. Tick verified only after you have checked them.</Notice><Table head={['Model', 'Capabilities', 'Verified', 'Enabled']}>{l.map((m: any) => <ModelRow key={m.id} m={m} name={names[m.provider_id]} />)}</Table></>}
          </Async>
        </TabPanel>
        <TabPanel id="usage">
          <Async q={use} isEmpty={() => false}>
            {(u) => (
              <Panel title="Token usage">
                <KV rows={[['Calls', u.total.calls], ['Prompt tokens', u.total.prompt_tokens], ['Completion tokens', u.total.completion_tokens], ['Cost', u.total.cost_usd == null ? 'Unknown (no pricing set)' : `$${u.total.cost_usd.toFixed(4)}`], ['Calls with unknown cost', u.total.unknown_cost_calls]]} />
                {Object.keys(u.by_model ?? {}).length > 0 && <pre className="mt-3 max-h-60 overflow-auto rounded-md bg-sunken p-2 text-xs">{JSON.stringify(u.by_model, null, 2)}</pre>}
              </Panel>
            )}
          </Async>
        </TabPanel>
      </Tabs>
      {edit && <ProviderForm initial={edit === 'new' ? undefined : edit} presets={pre.data ?? []} onClose={() => setEdit(null)} />}
    </>
  )
}
