import * as React from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import * as TabsP from '@radix-ui/react-tabs'
import * as SwitchP from '@radix-ui/react-switch'
import { cva, type VariantProps } from 'class-variance-authority'
import { AlertTriangle, Inbox, Loader2, X, KeyRound } from 'lucide-react'
import { cn } from '@/lib/utils'
import { errText } from '@/lib/hooks'

const btn = cva(
  'inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors disabled:opacity-50 disabled:pointer-events-none px-3.5 h-9 whitespace-nowrap',
  {
    variants: {
      variant: {
        primary: 'bg-brand text-brand-ink hover:opacity-90',
        outline: 'border border-line bg-surface hover:bg-sunken',
        ghost: 'hover:bg-sunken',
        danger: 'bg-danger text-brand-ink hover:opacity-90',
      },
      size: { sm: 'h-8 px-2.5 text-[13px]', md: '', icon: 'h-9 w-9 px-0' },
    },
    defaultVariants: { variant: 'outline', size: 'md' },
  },
)
export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof btn> { busy?: boolean }
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant, size, busy, children, disabled, ...p }, ref) => (
  <button ref={ref} className={cn(btn({ variant, size }), className)} disabled={disabled || busy} {...p}>
    {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
    {children}
  </button>
))
Button.displayName = 'Button'

const tones = {
  neutral: 'bg-sunken text-muted',
  brand: 'bg-brand-soft text-brand',
  ok: 'bg-ok-soft text-ok',
  warn: 'bg-warn-soft text-warn',
  danger: 'bg-danger-soft text-danger',
}
export type Tone = keyof typeof tones
export function Badge({ tone = 'neutral', className, ...p }: React.HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return <span className={cn('inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium', tones[tone], className)} {...p} />
}

export function statusTone(s?: string | null): Tone {
  const v = (s ?? '').toLowerCase()
  if (['confirmed', 'granted', 'ok', 'succeeded', 'success', 'satisfied', 'implemented', 'open', 'completed', 'done', 'healthy'].includes(v)) return 'ok'
  if (['proposed', 'pending', 'running', 'unknown', 'needs_user', 'needs_confirmation', 'experimental', 'paused', 'unverified', 'sensitive'].includes(v)) return 'warn'
  if (['rejected', 'denied', 'failed', 'error', 'not_satisfied', 'blocked', 'expired', 'cancelled', 'closed', 'unsupported'].includes(v)) return 'danger'
  return 'neutral'
}
export const StatusBadge = ({ status }: { status?: string | null }) => <Badge tone={statusTone(status)}>{(status ?? 'n/a').replace(/_/g, ' ')}</Badge>

export const Card = ({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) => (
  <section className={cn('rounded-card border border-line bg-surface', className)} {...p} />
)
export function Panel({ title, action, children, className }: { title?: React.ReactNode; action?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <Card className={cn('p-4', className)}>
      {(title || action) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 className="text-base font-semibold">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </Card>
  )
}

const field = 'w-full rounded-md border border-line bg-surface px-3 text-sm placeholder:text-muted/70 focus-visible:outline-brand disabled:opacity-60'
export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(({ className, ...p }, r) => (
  <input ref={r} className={cn(field, 'h-9', className)} {...p} />
))
Input.displayName = 'Input'
export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...p }, r) => (
  <textarea ref={r} className={cn(field, 'py-2', className)} {...p} />
))
Textarea.displayName = 'Textarea'
export const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(({ className, ...p }, r) => (
  <select ref={r} className={cn(field, 'h-9 pr-8', className)} {...p} />
))
Select.displayName = 'Select'

export function Field({ label, hint, children, className }: { label: string; hint?: string; children: React.ReactNode; className?: string }) {
  const id = React.useId()
  return (
    <div className={cn('space-y-1', className)}>
      <label htmlFor={id} className="text-[13px] font-medium">{label}</label>
      {React.isValidElement(children) ? React.cloneElement(children as React.ReactElement<any>, { id }) : children}
      {hint && <p className="text-xs text-muted">{hint}</p>}
    </div>
  )
}

/** Write-only secret field: never receives or renders an existing value. */
export function SecretInput({ hasSecret, value, onChange, label = 'API key' }: { hasSecret: boolean; value: string; onChange: (v: string) => void; label?: string }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <label htmlFor="secret-input" className="text-[13px] font-medium">{label}</label>
        {hasSecret && <Badge tone="ok"><KeyRound className="h-3 w-3" aria-hidden />secret set</Badge>}
      </div>
      <Input id="secret-input" type="password" autoComplete="new-password" value={value} onChange={(e) => onChange(e.target.value)}
        placeholder={hasSecret ? 'Enter a new key to replace it' : 'Paste key (stored encrypted, never shown again)'} />
      <p className="text-xs text-muted">Keys are write-only. Leave empty to keep the current one.</p>
    </div>
  )
}

export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <SwitchP.Root checked={checked} onCheckedChange={onChange} aria-label={label}
      className="relative h-5 w-9 shrink-0 rounded-full bg-sunken border border-line data-[state=checked]:bg-brand transition-colors">
      <SwitchP.Thumb className="block h-4 w-4 translate-x-0.5 rounded-full bg-surface shadow transition-transform data-[state=checked]:translate-x-[18px]" />
    </SwitchP.Root>
  )
}

export function Tabs({ tabs, value, onValueChange, children }: { tabs: { id: string; label: string }[]; value?: string; onValueChange?: (v: string) => void; children: React.ReactNode }) {
  return (
    <TabsP.Root value={value} onValueChange={onValueChange} defaultValue={value ? undefined : tabs[0].id}>
      <TabsP.List className="mb-4 flex gap-1 overflow-x-auto border-b border-line" aria-label="Sections">
        {tabs.map((t) => (
          <TabsP.Trigger key={t.id} value={t.id}
            className="-mb-px whitespace-nowrap border-b-2 border-transparent px-3 py-2 text-sm text-muted hover:text-ink data-[state=active]:border-brand data-[state=active]:text-ink data-[state=active]:font-medium">
            {t.label}
          </TabsP.Trigger>
        ))}
      </TabsP.List>
      {children}
    </TabsP.Root>
  )
}
export const TabPanel = ({ id, children }: { id: string; children: React.ReactNode }) => <TabsP.Content value={id}>{children}</TabsP.Content>

export function Modal({ open, onOpenChange, title, description, children, wide }: { open: boolean; onOpenChange: (o: boolean) => void; title: string; description?: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/50" />
        <Dialog.Content className={cn('fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-card border border-line bg-surface p-5 shadow-xl', wide ? 'max-w-3xl' : 'max-w-lg')}>
          <div className="mb-3 flex items-start justify-between gap-3">
            <Dialog.Title className="font-display text-lg font-semibold">{title}</Dialog.Title>
            <Dialog.Close asChild><Button variant="ghost" size="icon" aria-label="Close"><X className="h-4 w-4" /></Button></Dialog.Close>
          </div>
          <Dialog.Description className={description ? 'mb-3 text-sm text-muted' : 'sr-only'}>{description ?? title}</Dialog.Description>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return <div role="status" className="flex items-center gap-2 py-8 text-sm text-muted"><Loader2 className="h-4 w-4 animate-spin" aria-hidden />{label}...</div>
}
export function EmptyState({ title, children, action }: { title: string; children?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-card border border-dashed border-line px-6 py-10 text-center">
      <Inbox className="h-6 w-6 text-muted" aria-hidden />
      <p className="font-medium">{title}</p>
      {children && <p className="max-w-md text-sm text-muted">{children}</p>}
      {action}
    </div>
  )
}
export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const status = (error as any)?.status
  const missing = status === 404
  return (
    <div role="alert" className="flex items-start gap-3 rounded-card border border-danger/40 bg-danger-soft p-4 text-sm text-danger">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="space-y-1">
        <p className="font-medium">{missing ? 'This part of the API is not available yet' : 'Could not load this data'}</p>
        <p className="opacity-90">{missing ? 'The backend does not expose this endpoint in this build. The rest of the app still works.' : errText(error)}</p>
        {retry && <Button size="sm" variant="outline" onClick={retry}>Try again</Button>}
      </div>
    </div>
  )
}
/** Renders loading / error / empty / data for a TanStack query result. */
export function Async<T>({ q, empty, emptyTitle = 'Nothing here yet', emptyHint, isEmpty, children }: {
  q: { data?: T; isLoading: boolean; error: unknown; refetch: () => any }; empty?: React.ReactNode; emptyTitle?: string; emptyHint?: string
  isEmpty?: (d: T) => boolean; children: (d: T) => React.ReactNode
}) {
  if (q.isLoading) return <Spinner />
  if (q.error) return <ErrorState error={q.error} retry={() => q.refetch()} />
  const d = q.data as T
  if (d == null || (isEmpty ? isEmpty(d) : Array.isArray(d) && d.length === 0)) return <>{empty ?? <EmptyState title={emptyTitle}>{emptyHint}</EmptyState>}</>
  return <>{children(d)}</>
}

export function Notice({ tone = 'warn', children, className }: { tone?: 'warn' | 'brand' | 'danger'; children: React.ReactNode; className?: string }) {
  const c = { warn: 'bg-warn-soft text-warn', brand: 'bg-brand-soft text-brand', danger: 'bg-danger-soft text-danger' }[tone]
  return <div role="note" className={cn('rounded-md px-3 py-2 text-sm', c, className)}>{children}</div>
}

export function Meter({ value, max = 100, label }: { value: number; max?: number; label: string }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100))
  return (
    <div role="meter" aria-label={label} aria-valuenow={Math.round(value)} aria-valuemin={0} aria-valuemax={max} className="h-2 w-full overflow-hidden rounded-full bg-sunken">
      <div className="h-full rounded-full bg-brand" style={{ width: `${pct}%` }} />
    </div>
  )
}

export const Mono = ({ children, className }: { children: React.ReactNode; className?: string }) => <span className={cn('font-mono text-xs', className)}>{children}</span>

export function KV({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-sm">
      {rows.map(([k, v]) => (<React.Fragment key={k}><dt className="text-muted">{k}</dt><dd className="min-w-0 break-words">{v}</dd></React.Fragment>))}
    </dl>
  )
}

export function Table({ head, children }: { head: string[]; children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead><tr className="border-b border-line text-muted">{head.map((h) => <th key={h} className="px-2 py-2 font-medium">{h}</th>)}</tr></thead>
        <tbody className="[&_td]:px-2 [&_td]:py-2 [&_tr]:border-b [&_tr]:border-line/60">{children}</tbody>
      </table>
    </div>
  )
}
