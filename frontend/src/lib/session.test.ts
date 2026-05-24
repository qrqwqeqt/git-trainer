import { beforeEach, describe, expect, it } from 'vitest'

import {
  buildRoomWsUrl,
  buildSession,
  generateRoomId,
  getRoomLabel,
  getStoredUsername,
  hasStoredUsername,
  readUrlPrefill,
  sanitizeSlug,
  sanitizeUsername,
  saveRoomLabel,
  saveUsername,
} from './session'

beforeEach(() => {
  localStorage.clear()
  window.history.replaceState(null, '', '/')
})

describe('sanitizeSlug', () => {
  it('lowercases and replaces invalid chars with dashes', () => {
    expect(sanitizeSlug('Hello World')).toBe('hello-world')
    expect(sanitizeSlug('React Basics!')).toBe('react-basics-')
  })

  it('keeps latin, digits, dash, underscore', () => {
    expect(sanitizeSlug('a_b-c9')).toBe('a_b-c9')
  })

  it('caps length at 64', () => {
    expect(sanitizeSlug('x'.repeat(100))).toHaveLength(64)
  })
})

describe('sanitizeUsername', () => {
  it('trims and caps at 32', () => {
    expect(sanitizeUsername('  dzhe  ')).toBe('dzhe')
    expect(sanitizeUsername('y'.repeat(50))).toHaveLength(32)
  })

  it('falls back to guest on empty', () => {
    expect(sanitizeUsername('   ')).toBe('guest')
  })
})

describe('generateRoomId', () => {
  it('builds slug + 4-char suffix', () => {
    expect(generateRoomId('React Basics')).toMatch(/^react-basics-[a-z0-9]{4}$/)
  })

  it('falls back to room prefix when slug is empty', () => {
    expect(generateRoomId('!!!')).toMatch(/-[a-z0-9]{4}$/)
  })

  it('produces distinct ids on repeated calls', () => {
    expect(generateRoomId('x')).not.toBe(generateRoomId('x'))
  })
})

describe('room labels', () => {
  it('round-trips a human label for a roomId', () => {
    saveRoomLabel('react-basics-ab12', 'React Basics')
    expect(getRoomLabel('react-basics-ab12')).toBe('React Basics')
  })

  it('returns null for unknown room', () => {
    expect(getRoomLabel('nope')).toBeNull()
  })
})

describe('username storage', () => {
  it('saveUsername then getStoredUsername round-trip', () => {
    expect(hasStoredUsername()).toBe(false)
    saveUsername('dzhe')
    expect(getStoredUsername()).toBe('dzhe')
    expect(hasStoredUsername()).toBe(true)
  })
})

describe('buildSession', () => {
  it('generates and persists a stable userId', () => {
    const a = buildSession('room', 'dzhe')
    expect(a.roomId).toBe('room')
    expect(a.username).toBe('dzhe')
    expect(a.userId).toMatch(/^guest-/)
    // другий виклик переюзає той самий userId з localStorage
    const b = buildSession('other', 'bob')
    expect(b.userId).toBe(a.userId)
  })
})

describe('buildRoomWsUrl', () => {
  it('puts room in path and token in query', () => {
    const url = new URL(
      buildRoomWsUrl({ roomId: 'r1', userId: 'u', username: 'n' }, 'tok123'),
    )
    expect(url.pathname.endsWith('/ws/r1')).toBe(true)
    expect(url.searchParams.get('token')).toBe('tok123')
    // особистість не тече в query — лише токен
    expect(url.searchParams.get('username')).toBeNull()
  })
})

describe('readUrlPrefill', () => {
  it('reads room and name from URL', () => {
    window.history.replaceState(null, '', '/?room=demo&name=dzhe')
    expect(readUrlPrefill()).toEqual({ roomId: 'demo', username: 'dzhe' })
  })

  it('returns nulls when params absent', () => {
    expect(readUrlPrefill()).toEqual({ roomId: null, username: null })
  })
})
