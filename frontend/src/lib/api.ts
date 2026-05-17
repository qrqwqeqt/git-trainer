/** Тонкий API-клієнт. URL береться з env VITE_API_URL, fallback на localhost. */

const API_BASE: string =
  import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export async function resetSandbox(roomSlug: string): Promise<void> {
  const url = `${API_BASE}/rooms/${encodeURIComponent(roomSlug)}/sandbox`
  const res = await fetch(url, { method: 'DELETE' })
  if (!res.ok && res.status !== 204) {
    const body = await res.text()
    throw new Error(`reset failed: ${res.status} ${body}`)
  }
}
