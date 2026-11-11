import { get, post, put, del, api, items, download } from './client'

export type FeatureStatus = 'implemented' | 'experimental' | 'planned' | 'disabled' | string
export const features = () => api<Record<string, { label: string; status: FeatureStatus }>>('/features', {}, false)
export const authStatus = () => api<{ setup_required: boolean }>('/auth/status', {}, false)
export const login = (username: string, password: string) =>
  api<{ token: string }>('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }, false)
export const setup = (username: string, password: string) =>
  api<{ token: string }>('/auth/setup', { method: 'POST', body: JSON.stringify({ username, password }) }, false)
export const me = () => get<{ username: string }>('/auth/me')
export const dashboard = () => get<any>('/dashboard')
export const settings = () => get<Record<string, any>>('/settings')
export const putSetting = (k: string, value: unknown) => put(`/settings/${k}`, { value })
export const diagnostics = () => get<any>('/system/diagnostics')
export const logs = (limit = 100) => get<any>('/system/logs', { limit }).then((r) => items<any>(r))
export const events = (limit = 100) => get<any>('/system/events', { limit }).then((r) => items<any>(r))
export const backups = () => get<any>('/system/backups').then((r) => items<any>(r))
export const backupNow = () => post('/system/backup')
export const restore = (filename: string) => post('/system/restore', { filename })
export const exportAll = () => download('/system/export', 'careerpilot-export.zip')
export const deleteAll = () => del('/system/data', { confirm: 'DELETE' })
export const runs = (q: any = {}) => get<any>('/runs', q).then((r) => items<any>(r))
export const run = (id: string) => get<any>(`/runs/${id}`)
export const notifications = () => get<any>('/notifications')
export const markRead = (id: string) => post(`/notifications/${id}/read`)
