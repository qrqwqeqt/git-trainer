/** Тонкий API-клієнт. URL береться з env VITE_API_URL, fallback на localhost. */

const API_BASE: string =
  import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export interface AuthSessionResult {
  token: string
  user_id: string
  username: string
  room: string
  expires_at: string
}

/**
 * Отримати підписаний токен сесії для кімнати. Особистість (user_id/username)
 * видається й підписується сервером — далі WS приймає лише цей токен.
 */
export async function authSession(
  room: string,
  username: string,
  userId?: string,
): Promise<AuthSessionResult> {
  const res = await fetch(`${API_BASE}/auth/session`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ room, username, user_id: userId }),
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`auth failed: ${res.status} ${body}`)
  }
  return res.json() as Promise<AuthSessionResult>
}

export async function resetSandbox(roomSlug: string): Promise<void> {
  const url = `${API_BASE}/rooms/${encodeURIComponent(roomSlug)}/sandbox`
  const res = await fetch(url, { method: 'DELETE' })
  if (!res.ok && res.status !== 204) {
    const body = await res.text()
    throw new Error(`reset failed: ${res.status} ${body}`)
  }
}
