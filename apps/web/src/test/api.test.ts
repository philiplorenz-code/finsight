import { describe, expect, it, vi, beforeEach } from 'vitest'
import { api, ApiError, items, queryString, send, setCsrf } from '../lib/api'
describe('same-origin API security', () => {
  beforeEach(() => { setCsrf(); document.cookie = 'csrf_token=; Max-Age=0; path=/' })
  it('uses cookie sessions and a CSRF token returned by the server', async () => {
    const fetcher = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ csrf_token: 'synthetic-csrf' }), { status: 200 }))
    vi.stubGlobal('fetch', fetcher)
    await api('/auth/me'); await send('/accounts/a', { name: 'Synthetic' }, 'PATCH')
    const [url, request] = fetcher.mock.calls[1]
    expect(url).toBe('/api/accounts/a')
    expect(request.credentials).toBe('same-origin')
    expect(request.headers.get('X-CSRF-Token')).toBe('synthetic-csrf')
    expect(request.headers.get('Content-Type')).toBe('application/json')
  })
  it('reads CSRF cookies and lets fetch generate multipart boundaries', async () => {
    document.cookie = 'csrf_token=cookie-csrf; path=/'
    const fetcher = vi.fn().mockResolvedValue(new Response('{}'))
    vi.stubGlobal('fetch', fetcher)
    const body = new FormData(); body.append('file', new File(['synthetic'], 'synthetic.xlsx'))
    await api('/imports/preview', { method: 'POST', body })
    expect(fetcher.mock.calls[0][1].headers.get('X-CSRF-Token')).toBe('cookie-csrf')
    expect(fetcher.mock.calls[0][1].headers.has('Content-Type')).toBe(false)
    document.cookie = 'csrf_token=; Max-Age=0; path=/'
  })
  it('does not expose server exception details', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"detail":"private-secret"}', { status: 500 })))
    await expect(api('/accounts')).rejects.toEqual(new ApiError(500, 'unavailable'))
  })
  it.each(['https://external.invalid', '//external.invalid'])('rejects external paths %s', async path => {
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher)
    await expect(api(path)).rejects.toThrow('same-origin'); expect(fetcher).not.toHaveBeenCalled()
  })
  it('handles no-content mutations', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
    expect(await send('/auth/logout')).toBeUndefined()
  })
  it('normalizes list envelopes and escapes query text', () => {
    expect(items({ items: ['a'] })).toEqual(['a'])
    expect(queryString({ search: 'A&B', page: 1, absent: undefined })).toBe('?search=A%26B&page=1')
  })
})
