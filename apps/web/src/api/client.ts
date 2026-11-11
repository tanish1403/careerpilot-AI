// Typed fetch wrapper. Token lives in memory + sessionStorage (never localStorage).
const KEY = 'cp.token'
let token: string | null = null
try { token = sessionStorage.getItem(KEY) } catch { /* private mode */ }
let onUnauthorized: (() => void) | null = null

export const BASE = '/api/v1'

export function getToken() { return token }
export function setToken(t: string | null) {
  token = t
  try { if (t) sessionStorage.setItem(KEY, t); else sessionStorage.removeItem(KEY) } catch { /* ignore */ }
}
export function setUnauthorizedHandler(fn: (() => void) | null) { onUnauthorized = fn }

export class ApiError extends Error {
  constructor(public status: number, message: string, public code?: string, public body?: any) {
    super(message)
  }
}

export type Query = Record<string, string | number | boolean | undefined | null>
export function qs(q?: Query) {
  if (!q) return ''
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== null && v !== '') p.set(k, String(v))
  const s = p.toString()
  return s ? `?${s}` : ''
}

function detailText(d: any): string {
  if (!d) return 'Request failed'
  if (typeof d === 'string') return d
  if (Array.isArray(d)) return d.map((x) => x.msg ?? JSON.stringify(x)).join('; ')
  return JSON.stringify(d)
}

export async function raw(path: string, init: RequestInit = {}, auth = true): Promise<Response> {
  const headers = new Headers(init.headers)
  if (auth && token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type'))
    headers.set('Content-Type', 'application/json')
  let res: Response
  try {
    res = await fetch(BASE + path, { ...init, headers })
  } catch {
    throw new ApiError(0, 'Cannot reach the CareerPilot API. Is the backend running?')
  }
  if (res.status === 401 && auth) {
    setToken(null)
    onUnauthorized?.()
  }
  if (!res.ok) {
    let body: any = null
    try { body = await res.json() } catch { /* not json */ }
    throw new ApiError(res.status, detailText(body?.detail ?? body) || res.statusText, body?.code, body)
  }
  return res
}

export async function api<T = any>(path: string, init: RequestInit = {}, auth = true): Promise<T> {
  const res = await raw(path, init, auth)
  if (res.status === 204) return undefined as T
  const ct = res.headers.get('content-type') ?? ''
  return (ct.includes('json') ? res.json() : res.text()) as Promise<T>
}

export const get = <T = any>(path: string, q?: Query) => api<T>(path + qs(q))
export const post = <T = any>(path: string, body?: unknown) =>
  api<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
export const put = <T = any>(path: string, body?: unknown) =>
  api<T>(path, { method: 'PUT', body: JSON.stringify(body ?? {}) })
export const patch = <T = any>(path: string, body?: unknown) =>
  api<T>(path, { method: 'PATCH', body: JSON.stringify(body ?? {}) })
export const del = <T = any>(path: string, body?: unknown) =>
  api<T>(path, { method: 'DELETE', body: body === undefined ? undefined : JSON.stringify(body) })

/** Collections come back as {items,total} or a bare array depending on lane. */
export function items<T>(x: any): T[] {
  if (Array.isArray(x)) return x
  return (x?.items ?? []) as T[]
}

/** Download a binary/text endpoint with auth and hand it to the browser. */
export async function download(path: string, filename: string) {
  const res = await raw(path)
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
export async function blobUrl(path: string) {
  const res = await raw(path)
  return URL.createObjectURL(await res.blob())
}
