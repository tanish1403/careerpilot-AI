import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import * as E from '@/api/lanee'
import { Async, Badge, Button, Field, Input, Modal, Notice } from './ui'
import { useAct } from '@/lib/hooks'
import { GATED_STATES, legalTargets, sentence, fmtDate } from '@/lib/logic'

/** Offers only server-provided transitions. Approval-gated states are explained, never offered. */
export function MoveChoices({ current, allowed, onMove, busy }: { current: string; allowed: string[]; onMove: (to: string) => void; busy?: boolean }) {
  const targets = legalTargets(allowed, current)
  const gated = (allowed ?? []).filter((s) => GATED_STATES.includes(s))
  return (
    <div className="space-y-3">
      {targets.length === 0 ? <p className="text-sm text-muted">No moves are available from {sentence(current)}.</p> : (
        <ul className="flex flex-wrap gap-2" aria-label="Allowed moves">
          {targets.map((t) => <li key={t}><Button size="sm" busy={busy} onClick={() => onMove(t)}>{sentence(t)}</Button></li>)}
        </ul>
      )}
      {gated.length > 0 && <Notice tone="brand">{gated.map(sentence).join(' and ')} can only be reached through the resume and submit approval steps in the workspace.</Notice>}
    </div>
  )
}

function MoveDialog({ id, title, onClose }: { id: string; title: string; onClose: () => void }) {
  const [note, setNote] = useState('')
  const q = useQuery({ queryKey: ['application', id], queryFn: () => E.application(id) })
  const move = useAct((to: string) => E.transition(id, to, note || undefined), { ok: 'Application moved', invalidate: [['kanban'], ['application', id]], onDone: onClose })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`Move: ${title}`}>
      <Async q={q} isEmpty={() => false}>
        {(a) => (
          <div className="space-y-3">
            <p className="text-sm">Now in <Badge>{sentence(a.state)}</Badge></p>
            <Field label="Note (optional)"><Input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
            <MoveChoices current={a.state} allowed={a.allowed_transitions} busy={move.isPending} onMove={(to) => move.mutate(to)} />
          </div>
        )}
      </Async>
    </Modal>
  )
}

export function KanbanBoard({ columns, onOpen }: { columns: { state: string; items: E.KanbanCard[] }[]; onOpen: (id: string) => void }) {
  const [moving, setMoving] = useState<E.KanbanCard | null>(null)
  return (
    <>
      <div className="flex gap-3 overflow-x-auto pb-3" role="list" aria-label="Application stages">
        {columns.map((c) => (
          <section key={c.state} role="listitem" aria-label={sentence(c.state)} className="w-64 shrink-0 rounded-card bg-sunken p-2">
            <h3 className="flex items-center justify-between px-1 pb-2 text-sm font-semibold">{sentence(c.state)}<span className="text-xs font-normal text-muted tabular-nums">{c.items.length}</span></h3>
            <ul className="space-y-2">
              {c.items.map((it) => (
                <li key={it.id} className="rounded-md border border-line bg-surface p-2.5 text-sm">
                  <button className="block w-full text-left font-medium hover:underline" onClick={() => onOpen(it.id)}>{it.title}</button>
                  <p className="text-muted">{it.company_name}</p>
                  {it.follow_up_at && <p className="mt-1 text-xs text-warn">Follow up {fmtDate(it.follow_up_at)}</p>}
                  <Button size="sm" variant="ghost" className="mt-1 -ml-2" onClick={() => setMoving(it)}>Move</Button>
                </li>
              ))}
              {c.items.length === 0 && <li className="px-1 py-3 text-xs text-muted">Empty</li>}
            </ul>
          </section>
        ))}
      </div>
      {moving && <MoveDialog id={moving.id} title={moving.title} onClose={() => setMoving(null)} />}
    </>
  )
}
