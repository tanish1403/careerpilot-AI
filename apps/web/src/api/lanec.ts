import { get, post, put, patch, del, items } from './client'

export interface Match {
  id: string; job_id: string; eligibility: string; fit_score: number; priority_score: number
  eligibility_details: { requirement: string; state: string; evidence: any[]; reason?: string; mandatory?: boolean }[]
  factors: Record<string, { weight: number; score: number; contribution: number; evidence: any[]; note?: string; insufficient_data?: boolean }>
  missing: { requirement: string; kind?: string; mandatory?: boolean; reason?: string }[]
  disclaimer?: string
}
export interface JobSummary {
  id: string; title: string; company_name: string; location: string | null; work_mode: string | null
  posted_at: string | null; first_seen_at: string; last_verified_at: string | null; status: string; saved: boolean
  salary_text?: string | null; sources: { kind: string; url: string }[]
  match: { eligibility: string; fit_score: number; priority_score: number; id?: string } | null
}
export const sources = () => get<any>('/sources').then((r) => items<any>(r))
export const sourceKinds = () => get<any>('/sources/kinds')
export const createSource = (b: any) => post('/sources', b)
export const patchSource = (id: string, b: any) => patch(`/sources/${id}`, b)
export const deleteSource = (id: string) => del(`/sources/${id}`)
export const testSource = (id: string) => post<any>(`/sources/${id}/test`)
export const runSource = (id: string) => post<any>(`/sources/${id}/run`)
export const sourceHealth = (id: string) => get<any>(`/sources/${id}/health`)
export const ingestionLogs = () => get<any>('/ingestion-logs').then((r) => items<any>(r))
export const jobs = (q: any) => get<{ items: JobSummary[]; total: number }>('/jobs', q)
export const job = (id: string) => get<any>(`/jobs/${id}`)
export const importUrl = (url: string) => post<any>('/jobs/import-url', { url })
export const importText = (b: any) => post<any>('/jobs/import-text', b)
export const saveJob = (id: string, saved: boolean) => post(`/jobs/${id}/${saved ? 'unsave' : 'save'}`)
export const verifyJob = (id: string) => post<any>(`/jobs/${id}/verify`)
export const scoreAll = () => post<any>('/matches/score', { all: true })
export const scoreJobs = (job_ids: string[]) => post<any>('/matches/score', { job_ids })
export const matches = (job_id?: string) => get<any>('/matches', { job_id }).then((r) => items<Match>(r))
export const match = (id: string) => get<Match>(`/matches/${id}`)
export const feedback = (id: string, b: { relevant?: boolean; action?: string; reason?: string }) => post(`/matches/${id}/feedback`, b)
export const matchingConfig = () => get<{ weights: Record<string, number>; priority_weights?: Record<string, number>; version: string }>('/matching/config')
export const saveMatchingConfig = (b: any) => put('/matching/config', b)
