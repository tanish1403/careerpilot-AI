import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { WeightEditor } from '@/components/WeightEditor'
import { MoveChoices } from '@/components/Kanban'
import { SubmitReview } from '@/components/SubmitReview'
import { SecretInput } from '@/components/ui'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ProviderForm } from '@/pages/Models'
import { FeedbackPanels } from '@/pages/Interviews'
import { Brief } from '@/pages/Research'
import { ConfirmDelete } from '@/pages/System'
import { legalTargets, weightsValid, normalizeWeights, weightSum } from '@/lib/logic'

describe('weights', () => {
  it('validates the sum', () => {
    expect(weightsValid({ a: 0.5, b: 0.5 })).toBe(true)
    expect(weightsValid({ a: 0.5, b: 0.4 })).toBe(false)
    expect(weightsValid({ a: 1.2, b: -0.2 })).toBe(false)
    expect(weightSum(normalizeWeights({ a: 2, b: 1, c: 1 }))).toBeCloseTo(1, 6)
  })
  it('editor blocks save unless sum is 1 and can rescale', async () => {
    const onSave = vi.fn(); const u = userEvent.setup()
    render(<WeightEditor title="Fit weights" weights={{ a: 0.5, b: 0.5 }} onSave={onSave} />)
    const save = screen.getByRole('button', { name: 'Save weights' })
    expect(save).toBeEnabled()
    const a = screen.getByLabelText('A weight')
    await u.clear(a); await u.type(a, '0.8')
    expect(save).toBeDisabled()
    expect(screen.getByTestId('weight-sum')).toHaveTextContent('1.300')
    expect(screen.getByRole('note')).toHaveTextContent(/exactly 1/)
    await u.click(screen.getByRole('button', { name: 'Scale to 1' }))
    expect(save).toBeEnabled()
    await u.click(save)
    expect(onSave).toHaveBeenCalledOnce()
    expect(weightSum(onSave.mock.calls[0][0])).toBeCloseTo(1, 6)
  })
})

describe('kanban legal transitions', () => {
  it('only offers server-allowed targets, never gated states or the current one', () => {
    expect(legalTargets(['Shortlisted', 'Submitted', 'Approved', 'Rejected', 'Analyzed'], 'Analyzed')).toEqual(['Shortlisted', 'Rejected'])
    expect(legalTargets(undefined, 'X')).toEqual([])
  })
  it('renders exactly the allowed buttons and explains gated ones', async () => {
    const onMove = vi.fn(); const u = userEvent.setup()
    render(<MoveChoices current="ReviewRequired" allowed={['NeedsEdit', 'Approved', 'Cancelled']} onMove={onMove} />)
    const list = screen.getByRole('list', { name: 'Allowed moves' })
    expect(within(list).getAllByRole('button').map((b) => b.textContent)).toEqual(['Needs Edit', 'Cancelled'])
    expect(screen.queryByRole('button', { name: /approved/i })).toBeNull()
    expect(screen.getByRole('note')).toHaveTextContent(/approval steps/)
    await u.click(screen.getByRole('button', { name: 'Needs Edit' }))
    expect(onMove).toHaveBeenCalledWith('NeedsEdit')
  })
  it('shows an empty message when nothing is allowed', () => {
    render(<MoveChoices current="Blocked" allowed={[]} onMove={() => {}} />)
    expect(screen.getByText(/No moves are available/)).toBeInTheDocument()
  })
})

describe('secrets are write-only', () => {
  it('SecretInput shows a badge but never a value when a secret exists', () => {
    render(<SecretInput hasSecret value="" onChange={() => {}} />)
    expect(screen.getByText('secret set')).toBeInTheDocument()
    const input = screen.getByLabelText(/API key/) as HTMLInputElement
    expect(input.type).toBe('password'); expect(input.value).toBe('')
  })
  it('provider edit form never renders any key, even if the object carried one', () => {
    const p: any = { id: '1', display_name: 'P', protocol: 'openai_compatible', base_url: 'http://x', enabled: true, timeout_s: 60, max_retries: 2, local: false, has_secret: true, api_key: 'sk-LEAK-123', last_test_ok: null, last_test_at: null }
    render(<QueryClientProvider client={new QueryClient()}><ProviderForm initial={p} presets={[]} onClose={() => {}} /></QueryClientProvider>)
    expect(document.body.innerHTML).not.toContain('sk-LEAK-123')
    expect(screen.getByText('secret set')).toBeInTheDocument()
    expect((screen.getByLabelText(/API key/) as HTMLInputElement).value).toBe('')
  })
})

describe('submit approval review', () => {
  const snap = { resume_version_id: 'rv1', version_no: 3, destination_url: 'https://jobs.lever.co/acme/123', answers: [{ id: 'a1', question: 'Why Acme?', answer: 'Because of the mission.' }] }
  it('lists exact resume, answers and destination before the grant button', async () => {
    const onGrant = vi.fn(); const u = userEvent.setup()
    render(<SubmitReview snapshot={snap} resumeLabel="Version 3" onGrant={onGrant} onDeny={() => {}} />)
    const rv = screen.getByTestId('submit-review')
    expect(rv).toHaveTextContent('Version 3'); expect(rv).toHaveTextContent('rv1')
    expect(rv).toHaveTextContent('Why Acme?'); expect(rv).toHaveTextContent('Because of the mission.')
    expect(rv).toHaveTextContent('https://jobs.lever.co/acme/123')
    expect(rv).toHaveTextContent(/never submits for you/)
    expect(rv.textContent).not.toMatch(/auto-?submit/i)
    await u.click(screen.getByRole('button', { name: 'Grant submit approval' }))
    expect(onGrant).toHaveBeenCalled()
  })
  it('blocks granting without a resume or after invalidation', () => {
    const { rerender } = render(<SubmitReview snapshot={{ ...snap, resume_version_id: null }} onGrant={() => {}} />)
    expect(screen.getByRole('button', { name: 'Grant submit approval' })).toBeDisabled()
    rerender(<SubmitReview snapshot={{ ...snap, invalidated_reason: 'answers changed' }} onGrant={() => {}} />)
    expect(screen.getByRole('button', { name: 'Grant submit approval' })).toBeDisabled()
    expect(screen.getByText(/answers changed/)).toBeInTheDocument()
  })
})

describe('honest labelling', () => {
  it('keeps factual and communication feedback separate and flags unassessed answers', () => {
    const fb = { factual_correctness: { overall: null, note: 'Keyword-rubric', per_question: [{ question_id: 'b1', topic: 'behavioral', assessed: false, score: null, missing: [] }] }, communication: { overall: 0.4, avg_word_count: 14, notes: ['Too short'] }, revision_tasks: [] }
    render(<FeedbackPanels fb={fb} />)
    expect(screen.getByRole('heading', { name: 'Factual correctness' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Communication' })).toBeInTheDocument()
    expect(screen.getByText('Not assessed')).toBeInTheDocument()
    expect(screen.getByText('Too short')).toBeInTheDocument()
  })
  it('labels unsourced interview themes unverified and shows retrieval times', () => {
    const c = { name: 'Acme', claims: [{ text: 'Page title: Acme', source_url: 'https://acme.test', retrieved_at: '2026-01-02T03:04:00Z' }], sources: [{ url: 'https://acme.test', retrieved_at: '2026-01-02T03:04:00Z' }], interview_themes: [{ theme: 'System design', source_url: null, unverified: true, note: 'No source provided' }, { theme: 'SQL', source_url: 'https://acme.test/blog', retrieved_at: '2026-01-02T03:04:00Z', unverified: false }], fetches: [] }
    render(<Brief c={c} />)
    expect(screen.getAllByText('unverified')).toHaveLength(1)
    expect(screen.getByText('sourced')).toBeInTheDocument()
    expect(screen.getAllByText(/retrieved/).length).toBeGreaterThan(1)
  })
  it('delete-all needs the word DELETE', async () => {
    const onConfirm = vi.fn(); const u = userEvent.setup()
    render(<ConfirmDelete onConfirm={onConfirm} onClose={() => {}} />)
    const btn = screen.getByRole('button', { name: 'Delete everything' })
    expect(btn).toBeDisabled()
    await u.type(screen.getByLabelText(/Type DELETE/), 'delete')
    expect(btn).toBeDisabled()
    await u.clear(screen.getByLabelText(/Type DELETE/)); await u.type(screen.getByLabelText(/Type DELETE/), 'DELETE')
    expect(btn).toBeEnabled()
    await u.click(btn); expect(onConfirm).toHaveBeenCalled()
  })
})
