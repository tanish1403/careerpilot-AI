import { useState } from 'react'
import { Button, Input, Notice } from './ui'
import { normalizeWeights, weightSum, weightsValid, sentence } from '@/lib/logic'

/** Edits a weight map; Save is only possible when the weights sum to exactly 1. */
export function WeightEditor({ weights, onSave, busy, title }: { weights: Record<string, number>; onSave: (w: Record<string, number>) => void; busy?: boolean; title: string }) {
  const [w, setW] = useState<Record<string, number>>(weights)
  const sum = weightSum(w)
  const ok = weightsValid(w)
  return (
    <div className="space-y-3">
      <h3 className="font-display text-base font-semibold">{title}</h3>
      <div className="grid gap-2 sm:grid-cols-2">
        {Object.keys(w).map((k) => (
          <label key={k} className="flex items-center justify-between gap-3 text-sm">
            <span>{sentence(k)}</span>
            <Input type="number" step="0.01" min="0" max="1" className="w-24 tabular-nums" aria-label={`${sentence(k)} weight`}
              value={Number.isNaN(w[k]) ? '' : w[k]} onChange={(e) => setW({ ...w, [k]: e.target.value === '' ? NaN : parseFloat(e.target.value) })} />
          </label>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <span className={`text-sm tabular-nums ${ok ? 'text-ok' : 'text-danger'}`} data-testid="weight-sum">Sum: {sum.toFixed(3)}</span>
        <Button size="sm" variant="outline" onClick={() => setW(normalizeWeights(w))}>Scale to 1</Button>
        <Button variant="primary" size="sm" disabled={!ok} busy={busy} onClick={() => onSave(w)}>Save weights</Button>
      </div>
      {!ok && <Notice tone="danger">Weights must add up to exactly 1 (currently {sum.toFixed(3)}). Adjust them or use Scale to 1.</Notice>}
    </div>
  )
}
