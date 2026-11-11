import { get, post, put, patch, api, items, blobUrl } from './client'

export type FactStatus = 'proposed' | 'confirmed' | 'rejected'
export interface Fact {
  id: string; category: string; key: string | null; value: any; status: FactStatus
  confidence: number | null; source_document_id: string | null; source_location: any
}
export interface Claim { id: string; text: string; evidence_ids: string[]; needs_confirmation: boolean }
export interface ResumeVersion {
  id: string; version_no: number; label: string | null; job_id: string | null
  pdf_available: boolean; validation_report: any; needs_confirmation_count: number
  created_at: string; stale?: boolean; latex_source?: string; claims?: Claim[]; template_id?: string
}
export const profile = () => get<any>('/profiles/current')
export const saveProfile = (b: any) => put('/profiles/current', b)
export const facts = (q: any = {}) => get<any>('/facts', q).then((r) => items<Fact>(r))
export const confirmFact = (id: string) => post(`/facts/${id}/confirm`)
export const rejectFact = (id: string) => post(`/facts/${id}/reject`)
export const editFact = (id: string, value: any, confirm = false) => patch(`/facts/${id}`, { value, confirm })
export const documents = () => get<any>('/documents').then((r) => items<any>(r))
export const uploadDocument = (file: File, kind = 'resume') => {
  const f = new FormData(); f.append('file', file); f.append('kind', kind)
  return api<any>('/documents', { method: 'POST', body: f })
}
export const resumes = (job_id?: string) => get<any>('/resumes', { job_id }).then((r) => items<ResumeVersion>(r))
export const resume = (id: string) => get<ResumeVersion>(`/resumes/${id}`)
export const generateResume = (b: { job_id?: string; job_description?: string; template_id?: string; label?: string }) =>
  post<ResumeVersion>('/resumes/generate', b)
export const saveSource = (id: string, latex_source: string) => put<ResumeVersion>(`/resumes/${id}/source`, { latex_source })
export const compile = (id: string) => post<any>(`/resumes/${id}/compile`)
export const pdfUrl = (id: string) => blobUrl(`/resumes/${id}/pdf`)
export const diff = (id: string, against: string) => get<any>(`/resumes/${id}/diff`, { against })
export const restoreResume = (id: string) => post<ResumeVersion>(`/resumes/${id}/restore`)
export const confirmClaim = (id: string, claim: string) => post(`/resumes/${id}/claims/${claim}/confirm`)
export const templates = () => get<any>('/resume-templates').then((r) => items<any>(r))
export const coverLetter = (b: { job_id: string; resume_id?: string }) => post<any>('/cover-letters/generate', b)
