import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

// xterm/d3 важкі для jsdom — підміняємо дочірні компоненти та залежності.
vi.mock('../lib/api', () => ({
  authSession: vi.fn(),
  resetSandbox: vi.fn(),
}))
vi.mock('../hooks/useWebSocket', () => ({
  useWebSocket: () => ({ state: 'connecting', sendMessage: vi.fn() }),
}))
vi.mock('./GitGraph', () => ({ GitGraph: () => null }))
vi.mock('./Terminal', () => ({ Terminal: () => null }))

import { authSession } from '../lib/api'
import { Room } from './Room'

const session = { roomId: 'r', userId: 'u', username: 'n' }

beforeEach(() => {
  vi.clearAllMocks()
})

describe('Room auth state', () => {
  it('shows an auth-error indicator when authSession rejects', async () => {
    vi.mocked(authSession).mockRejectedValueOnce(new Error('boom'))
    render(<Room session={session} onSessionChange={vi.fn()} />)
    expect(await screen.findByText('помилка авторизації')).toBeTruthy()
  })

  it('does not show auth error on successful auth', async () => {
    vi.mocked(authSession).mockResolvedValueOnce({
      token: 'tok',
      user_id: 'u',
      username: 'n',
      room: 'r',
      expires_at: '',
    })
    render(<Room session={session} onSessionChange={vi.fn()} />)
    // дочекатись мікротасків auth-проміса
    await Promise.resolve()
    expect(screen.queryByText('помилка авторизації')).toBeNull()
  })
})
