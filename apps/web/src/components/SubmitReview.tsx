import { AlertTriangle } from 'lucide-react'
import { Badge, Button, Notice } from './ui'

export interface SubmitSnapshot {
  resume_version_id?: string | null; version_no?: number | null; destination_url?: string | null
  answers?: { id: string; question: string; answer: string | null }[]; invalidated_reason?: string
}

/**
 * Explicit review of the exact artefacts a submit approval covers.
 * Granting approval only lets YOU submit the form yourself; nothing here submits anything.
 */
export function SubmitReview({ snapshot, resumeLabel, onGrant, onDeny, busy }: {
  snapshot: SubmitSnapshot; resumeLabel?: string; onGrant?: () => void; onDeny?: () => void; busy?: boolean
}) {
  const answers = snapshot.answers ?? []
  return (
    <div className="space-y-4" data-testid="submit-review">
      <Notice tone="warn">
        <AlertTriangle className="mr-1 inline h-4 w-4" aria-hidden />
        Review exactly what you are approving. CareerPilot never submits for you: approving unlocks the
        final step, which you complete yourself on the employer page.
      </Notice>
      <section aria-labelledby="rv-resume">
        <h3 id="rv-resume" className="text-sm font-semibold">Resume</h3>
        <p className="text-sm">{snapshot.resume_version_id
          ? <>{resumeLabel ?? `Version ${snapshot.version_no ?? ''}`.trim()} <span className="font-mono text-xs text-muted">({snapshot.resume_version_id})</span></>
          : <Badge tone="danger">No resume selected</Badge>}</p>
      </section>
      <section aria-labelledby="rv-answers">
        <h3 id="rv-answers" className="text-sm font-semibold">Answers ({answers.length})</h3>
        {answers.length === 0 ? <p className="text-sm text-muted">No answers are attached.</p> : (
          <ul className="mt-1 space-y-2">
            {answers.map((a) => (
              <li key={a.id} className="rounded-md bg-sunken p-2 text-sm">
                <p className="text-muted">{a.question}</p>
                <p className="whitespace-pre-wrap">{a.answer ?? <em>No answer</em>}</p>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section aria-labelledby="rv-dest">
        <h3 id="rv-dest" className="text-sm font-semibold">Destination</h3>
        <p className="break-all font-mono text-sm">{snapshot.destination_url ?? 'Unknown'}</p>
      </section>
      {snapshot.invalidated_reason && <Notice tone="danger">This approval request is no longer valid: {snapshot.invalidated_reason}. Request it again.</Notice>}
      {(onGrant || onDeny) && (
        <div className="flex flex-wrap gap-2">
          {onGrant && <Button variant="primary" busy={busy} disabled={!snapshot.resume_version_id || !!snapshot.invalidated_reason} onClick={onGrant}>Grant submit approval</Button>}
          {onDeny && <Button variant="outline" busy={busy} onClick={onDeny}>Deny</Button>}
        </div>
      )}
    </div>
  )
}
