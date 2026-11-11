import { get, post, put, patch, del, items } from './client'

export interface Provider {
  id: string; display_name: string; protocol: string; base_url: string; enabled: boolean
  timeout_s: number; max_retries: number; local: boolean; has_secret: boolean
  last_test_ok: boolean | null; last_test_at: string | null
}
export const providers = () => get<any>('/providers').then((r) => items<Provider>(r))
export const presets = () => get<any>('/providers/presets').then((r) => items<any>(r))
export const createProvider = (b: any) => post<Provider>('/providers', b)
export const patchProvider = (id: string, b: any) => patch<Provider>(`/providers/${id}`, b)
export const deleteProvider = (id: string) => del(`/providers/${id}`)
export const testProvider = (id: string) => post<any>(`/providers/${id}/test`)
export const discover = (id: string) => post<any>(`/providers/${id}/discover`)
export const models = () => get<any>('/models').then((r) => items<any>(r))
export const patchModel = (id: string, b: any) => patch(`/models/${id}`, b)
export const usage = () => get<any>('/usage')
export const agents = () => get<any>('/agents').then((r) => items<any>(r))
export const agentConfig = (n: string) => get<any>(`/agents/${n}/config`)
export const saveAgentConfig = (n: string, b: any) => put(`/agents/${n}/config`, b)
export const runAgent = (n: string, input: any) => post<any>(`/agents/${n}/run`, { input })
export const runControl = (id: string, a: 'pause' | 'resume' | 'cancel') => post(`/runs/${id}/${a}`)
export const workflows = () => get<any>('/workflows').then((r) => items<any>(r))
export const createWorkflow = (b: any) => post('/workflows', b)
export const runWorkflow = (id: string, inputs: any) => post<any>(`/workflows/${id}/run`, { inputs })
export const workflowRun = (id: string) => get<any>(`/workflow-runs/${id}`)
export const checkpoints = (id: string) => get<any>(`/workflow-runs/${id}/checkpoints`).then((r) => items<any>(r))
export const approveWorkflow = (id: string, approve: boolean, comment?: string) => post(`/workflow-runs/${id}/approve`, { approve, comment })
export const approvals = (status?: string) => get<any>('/approvals', { status }).then((r) => items<any>(r))
export const decide = (id: string, grant: boolean) => post(`/approvals/${id}/decide`, { grant })
