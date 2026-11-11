export const DISCLAIMER = 'This is a decision-support signal, not a probability of selection.'

/** States that can never be chosen from the generic move menu (server enforces too). */
export const GATED_STATES = ['Submitted', 'Approved']

/** Kanban: offer ONLY server-provided allowed transitions, minus approval-gated states. */
export function legalTargets(allowed: string[] | undefined | null, current: string): string[] {
  return (allowed ?? []).filter((s) => s !== current && !GATED_STATES.includes(s))
}

export function weightSum(w: Record<string, number>): number {
  return Object.values(w).reduce((a, b) => a + (Number.isFinite(b) ? b : 0), 0)
}
export function weightsValid(w: Record<string, number>, eps = 0.001): boolean {
  return Math.abs(weightSum(w) - 1) <= eps && Object.values(w).every((x) => Number.isFinite(x) && x >= 0)
}
/** Scale all weights so they sum to exactly 1 (rounded to 3 dp; last key absorbs drift). */
export function normalizeWeights(w: Record<string, number>): Record<string, number> {
  const keys = Object.keys(w)
  const s = weightSum(w)
  if (!s || !keys.length) return w
  const out: Record<string, number> = {}
  let acc = 0
  keys.forEach((k, i) => {
    out[k] = i === keys.length - 1 ? Math.round((1 - acc) * 1000) / 1000 : Math.round((w[k] / s) * 1000) / 1000
    acc += out[k]
  })
  return out
}

export const pretty = (s: string) => s.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/_/g, ' ')
export const sentence = (s: string) => { const p = pretty(s); return p.charAt(0).toUpperCase() + p.slice(1) }

export function fmtDate(s?: string | null) {
  if (!s) return 'n/a'
  const d = new Date(s)
  return isNaN(+d) ? s : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}
export function fmtBytes(n?: number) {
  if (n == null) return 'n/a'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++ }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`
}
export function factText(v: any): string {
  if (v == null) return ''
  if (typeof v === 'string') return v
  if (typeof v === 'object') {
    return Object.entries(v).filter(([, x]) => x != null && x !== '' && !(Array.isArray(x) && !x.length))
      .map(([k, x]) => `${pretty(k)}: ${Array.isArray(x) ? x.join(', ') : typeof x === 'object' ? JSON.stringify(x) : x}`).join(' | ')
  }
  return String(v)
}
