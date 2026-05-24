/**
 * Утиліти для початкової сесії: підбір room/user/username з URL і
 * формування WebSocket URL. Серверний endpoint:
 *   GET /ws/{room_id}?user_id=...&username=...
 *
 * Архітектура:
 *   - URL — джерело правди для roomId та username (share-able).
 *   - localStorage — кеш guest-id, останнього username і людських
 *     назв кімнат (room labels). На бек не передається.
 *   - App.tsx вирішує, чи показувати Landing або одразу Room
 *     на основі readUrlPrefill() + getStoredUsername().
 */

const WS_BASE: string =
  import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000/ws'

const GUEST_ID_KEY = 'git-trainer.guestId'
const GUEST_NAME_KEY = 'git-trainer.guestName'
const ROOM_LABELS_KEY = 'git-trainer.roomLabels'

const ID_ALPHABET = 'abcdefghijkmnpqrstuvwxyz23456789'
const ROOM_SUFFIX_LEN = 4

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

export interface UrlPrefill {
  roomId: string | null
  username: string | null
}

/** Читає сирі ?room= і ?name= з URL без жодних fallback-ів. */
export function readUrlPrefill(): UrlPrefill {
  const params = new URLSearchParams(window.location.search)
  return {
    roomId: params.get('room')?.trim() || null,
    username: params.get('name')?.trim() || null,
  }
}

/** localStorage username (null якщо ще не зберігали). */
export function getStoredUsername(): string | null {
  const v = localStorage.getItem(GUEST_NAME_KEY)
  return v && v.trim() ? v.trim() : null
}

export function hasStoredUsername(): boolean {
  return getStoredUsername() !== null
}

/** Збирає повний SessionInfo: roomId/username задані, userId — з кешу або новий. */
export function buildSession(roomId: string, username: string): SessionInfo {
  let userId = localStorage.getItem(GUEST_ID_KEY) ?? ''
  if (!userId) {
    userId = `guest-${randomId(6)}`
    localStorage.setItem(GUEST_ID_KEY, userId)
  }
  return { roomId, userId, username }
}

/** Збирає WS URL виду ws://host/ws/{room}?token=...
 *  Особистість тепер у підписаному токені (див. lib/api.authSession),
 *  а не в сирих query-параметрах — клієнт не може її підмінити.
 */
export function buildRoomWsUrl(session: SessionInfo, token: string): string {
  const url = new URL(WS_BASE)
  const cleanPath = url.pathname.replace(/\/+$/, '')
  url.pathname = `${cleanPath}/${encodeURIComponent(session.roomId)}`
  url.searchParams.set('token', token)
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

/** Згенерувати roomId з людської назви: slug + випадковий суфікс,
 *  щоб «react basics» від двох викладачів не злилися в одну кімнату.
 */
export function generateRoomId(displayName: string): string {
  const slug = sanitizeSlug(displayName)
  const suffix = randomId(ROOM_SUFFIX_LEN)
  const base = slug || 'room'
  return `${base}-${suffix}`.slice(0, 64)
}

// ---------------- Room labels (людська назва ↔ roomId) ----------------

function readRoomLabels(): Record<string, string> {
  try {
    const raw = localStorage.getItem(ROOM_LABELS_KEY)
    if (!raw) return {}
    const parsed: unknown = JSON.parse(raw)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as Record<string, string>
    }
    return {}
  } catch {
    return {}
  }
}

export function saveRoomLabel(roomId: string, label: string): void {
  const labels = readRoomLabels()
  labels[roomId] = label.trim().slice(0, 64)
  try {
    localStorage.setItem(ROOM_LABELS_KEY, JSON.stringify(labels))
  } catch {
    /* приватний режим або quota — мовчки ігноруємо, не критично */
  }
}

export function getRoomLabel(roomId: string): string | null {
  return readRoomLabels()[roomId] ?? null
}
