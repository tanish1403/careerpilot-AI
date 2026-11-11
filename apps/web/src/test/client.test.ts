import { describe, it, expect, vi, beforeEach } from 'vitest'
import { api, get, setToken, getToken, setUnauthorizedHandler, ApiError } from '@/api/client'

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

describe('api client auth', () => {
  beforeEach(() => { setToken(null); setUnauthorizedHandler(null); vi.restoreAllMocks() })

  it('sends the bearer token and stores it in sessionStorage only', async () => {
    setToken('abc')
    expect(sessionStorage.getItem('cp.token')).toBe('abc')
    expect(localStorage.getItem('cp.token')).toBeNull()
    const f = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(200, { ok: 1 }))
    await get('/profiles/current')
    const [url, init] = f.mock.calls[0]
    expect(url).toBe('/api/v1/profiles/current')
    expect(new Headers((init as RequestInit).headers).get('Authorization')).toBe('Bearer abc')
  })

  it('omits the token on public calls', async () => {
    setToken('abc')
    const f = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(200, {}))
    await api('/auth/status', {}, false)
    expect(new Headers((f.mock.calls[0][1] as RequestInit).headers).has('Authorization')).toBe(false)
  })

  it('on 401 clears the token and calls the unauthorized handler (back to login)', async () => {
    setToken('abc')
    const h = vi.fn(); setUnauthorizedHandler(h)
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(401, { detail: 'Not authenticated' }))
    await expect(get('/jobs')).rejects.toMatchObject({ status: 401 })
    expect(getToken()).toBeNull()
    expect(sessionStorage.getItem('cp.token')).toBeNull()
    expect(h).toHaveBeenCalledOnce()
  })

  it('surfaces the server detail and code in ApiError', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(422, { detail: 'bad file', code: 'unsupported_type' }))
    const e = await get('/x').catch((x) => x)
    expect(e).toBeInstanceOf(ApiError)
    expect(e.message).toBe('bad file'); expect(e.code).toBe('unsupported_type')
  })

  it('explains a network failure', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('fail'))
    await expect(get('/x')).rejects.toThrow(/Cannot reach/)
  })
})
