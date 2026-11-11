import { get, post, put, patch, items } from './client'

export interface AppAnswer {
  id: string; question: string; answer: string | null; sensitive: boolean; needs_user: boolean
  user_confirmed: boolean; evidence_ids: string[]; category?: string
}
export interface Application {
  id: string; job_id: string; state: string; resume_version_id: string | null; destination_url: string | null
  notes: string | null; follow_up_at: string | null; submitted_at: string | null; confirmation_ref: string | null
  job: { id: string; title: string; company_name: string; location: string | null; canonical_url: string | null } | null
  resume_version: { id: string; version_no: number; label: string | null } | null
  answers: AppAnswer[]; events: { id: string; kind: string; from_state: string | null; to_state: string | null; actor: string; created_at: string; detail: any }[]
  allowed_transitions: string[]; blockers: any[]; submit_approval: { id: string; status: string } | null
}
export interface KanbanCard { id: string; job_id: string; title: string; company_name: string; state: string; follow_up_at: string | null; updated_at: string }
export const kanban = () => get<{ columns: { state: string; items: KanbanCard[] }[] }>('/applications/kanban')
export const applications = () => get<any>('/applications').then((r) => items<any>(r))
export const application = (id: string) => get<Application>(`/applications/${id}`)
export const createApplication = (job_id: string) => post<any>('/applications', { job_id })
export const transition = (id: string, to_state: string, note?: string) => post(`/applications/${id}/transition`, { to_state, note })
export const patchApplication = (id: string, b: any) => patch(`/applications/${id}`, b)
export const prepare = (id: string) => post<any>(`/applications/${id}/prepare`)
export const saveAnswers = (id: string, answers: { id?: string; question?: string; answer: string }[]) => put(`/applications/${id}/answers`, { answers })
export const confirmAnswer = (id: string) => post(`/answers/${id}/confirm`)
export const approveResume = (id: string, resume_version_id: string) => post(`/applications/${id}/approve-resume`, { resume_version_id })
export const requestSubmit = (id: string) => post<any>(`/applications/${id}/request-submit`)
export const confirmSubmitted = (id: string, approval_id: string, confirmation_ref?: string) => post(`/applications/${id}/confirm-submitted`, { approval_id, confirmation_ref })
export const startSession = (application_id: string) => post<any>('/automation/sessions', { application_id })
export const session = (id: string) => get<any>(`/automation/sessions/${id}`)
export const fillPreview = (id: string) => post<any>(`/automation/sessions/${id}/fill-preview`)
export const autofill = (id: string) => post<any>(`/automation/sessions/${id}/autofill`)
export const stopSession = (id: string) => post<any>(`/automation/sessions/${id}/stop`)
export const allowlist = () => get<{ domains: string[]; default: string[] }>('/automation/allowlist')
export const saveAllowlist = (domains: string[]) => put('/automation/allowlist', { domains })
export const adapters = () => get<any>('/automation/adapters').then((r) => items<any>(r))
