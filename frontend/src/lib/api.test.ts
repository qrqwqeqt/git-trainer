import { afterEach, describe, expect, it, vi } from 'vitest'

import { authSession, resetSandbox } from './api'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('authSession', () => {
  it('POSTs to /auth/session and returns the token payload', async () => {
    const payload = {
      token: 'tok',
      user_id: 'u',
      username: 'n',
      room: 'r',
      expires_at: '2026-01-01T00:00:00Z',
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(payload),
    })
    vi.stubGlobal('fetch', fetchMock)

    const res = await authSession('r', 'n', 'u')
    expect(res.token).toBe('tok')

    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(String(url)).toContain('/auth/session')
    expect(opts.method).toBe('POST')
    expect(JSON.parse(String(opts.body))).toEqual({
      room: 'r',
      username: 'n',
      user_id: 'u',
    })
  })

  it('throws on non-ok response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        text: () => Promise.resolve('unauthorized'),
      }),
    )
    await expect(authSession('r', 'n')).rejects.toThrow(/auth failed/)
  })
})

describe('resetSandbox', () => {
  it('sends DELETE to the room sandbox', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204 })
    vi.stubGlobal('fetch', fetchMock)

    await resetSandbox('demo')
    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(String(url)).toContain('/rooms/demo/sandbox')
    expect(opts.method).toBe('DELETE')
  })

  it('throws on error status', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        text: () => Promise.resolve('bad gateway'),
      }),
    )
    await expect(resetSandbox('demo')).rejects.toThrow(/reset failed/)
  })
})
