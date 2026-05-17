/**
 * Утиліти для початкової сесії: підбір room/user/username з URL і
 * формування WebSocket URL. Серверний endpoint:
 *   GET /ws/{room_id}?user_id=...&username=...
 */

const WS_BASE: string =
  import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000/ws'

const GUEST_ID_KEY = 'git-trainer.guestId'
const GUEST_NAME_KEY = 'git-trainer.guestName'

const ID_ALPHABET = 'abcdefghijkmnpqrstuvwxyz23456789'

function randomId(len = 6): string {
  let out = ''
  for (let i = 0; i < len; i += 1) {
    out += ID_ALPHABET[Math.floor(Math.random() * ID_ALPHABET.length)]
  }
  return out
}

export interface SessionInfo {
  roomId: string
  userId: string
  username: string
}

/**
 * Дістає room/user/username з URL-параметрів (?room=, ?user=, ?name=);
 * відсутні значення підтягуються з localStorage або генеруються вперше.
 * guest-id зберігається у localStorage, щоб refresh не робив тебе іншим
 * юзером (інакше backend бачитиме нескінченний потік USER_JOINED).
 */
export function readSessionFromUrl(): SessionInfo {
  const params = new URLSearchParams(window.location.search)

  const roomId = params.get('room')?.trim() || 'demo'

  let userId = params.get('user')?.trim() || ''
  if (!userId) {
    userId = localStorage.getItem(GUEST_ID_KEY) ?? ''
    if (!userId) {
      userId = `guest-${randomId(6)}`
      localStorage.setItem(GUEST_ID_KEY, userId)
    }
  }

  let username = params.get('name')?.trim() || ''
  if (!username) {
    username = localStorage.getItem(GUEST_NAME_KEY) ?? userId
    if (!localStorage.getItem(GUEST_NAME_KEY)) {
      localStorage.setItem(GUEST_NAME_KEY, username)
    }
  }

  return { roomId, userId, username }
}

/** Збирає WS URL виду ws://host/ws/{room}?user_id=...&username=... */
export function buildRoomWsUrl(session: SessionInfo): string {
  const url = new URL(WS_BASE)
  const cleanPath = url.pathname.replace(/\/+$/, '')
  url.pathname = `${cleanPath}/${encodeURIComponent(session.roomId)}`
  url.searchParams.set('user_id', session.userId)
  url.searchParams.set('username', session.username)
  return url.toString()
}

/** Зберегти username (для guest) — щоб refresh не давав нове імʼя. */
export function saveUsername(username: string): void {
  if (username.trim()) {
    localStorage.setItem(GUEST_NAME_KEY, username.trim())
  }
}

/** Записати поточний room/username у URL — щоб посилання було share-able.
 *  Використовуємо replaceState, бо це не «нова сторінка», а зміна стану.
 */
export function updateUrlForSession(session: SessionInfo): void {
  const url = new URL(window.location.href)
  url.searchParams.set('room', session.roomId)
  url.searchParams.set('name', session.username)
  window.history.replaceState(null, '', url.toString())
}

/** Простий sanitizer для room slug та username: тільки latin/digits/-/_. */
export function sanitizeSlug(raw: string): string {
  return raw.trim().toLowerCase().replace(/[^a-z0-9_-]/g, '-').slice(0, 64)
}

export function sanitizeUsername(raw: string): string {
  return raw.trim().slice(0, 32) || 'guest'
}
