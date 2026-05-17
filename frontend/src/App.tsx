import { useCallback, useEffect, useState } from 'react'

import { Landing } from './components/Landing'
import { Room } from './components/Room'
import {
  buildSession,
  getStoredUsername,
  readUrlPrefill,
  saveRoomLabel,
  saveUsername,
  updateUrlForSession,
  type SessionInfo,
} from './lib/session'

type View =
  | { kind: 'landing'; prefillRoom: string | null }
  | { kind: 'room'; session: SessionInfo }

/** Вирішує, що показувати при старті/після popstate: лендинг чи комната.
 *  Правило: якщо в URL є ?room= і ми знаємо username (URL/localStorage) —
 *  стрибаємо одразу в кімнату; інакше — лендинг (можливо з prefill).
 */
function resolveView(): View {
  const { roomId, username } = readUrlPrefill()
  const effectiveUsername = username ?? getStoredUsername()
  if (roomId && effectiveUsername) {
    const session = buildSession(roomId, effectiveUsername)
    saveUsername(effectiveUsername)
    updateUrlForSession(session)
    return { kind: 'room', session }
  }
  return { kind: 'landing', prefillRoom: roomId }
}

function App() {
  const [view, setView] = useState<View>(resolveView)

  // back/forward-кнопки браузера: перерахуємо view з URL.
  useEffect(() => {
    const handler = () => setView(resolveView())
    window.addEventListener('popstate', handler)
    return () => window.removeEventListener('popstate', handler)
  }, [])

  const handleSessionChange = useCallback((next: SessionInfo) => {
    saveUsername(next.username)
    updateUrlForSession(next)
    setView({ kind: 'room', session: next })
  }, [])

  const handleEnter = useCallback(
    (opts: { roomId: string; username: string; label?: string }) => {
      saveUsername(opts.username)
      if (opts.label) saveRoomLabel(opts.roomId, opts.label)
      const session = buildSession(opts.roomId, opts.username)
      updateUrlForSession(session)
      setView({ kind: 'room', session })
    },
    [],
  )

  if (view.kind === 'landing') {
    return <Landing prefillRoom={view.prefillRoom} onEnter={handleEnter} />
  }
  return <Room session={view.session} onSessionChange={handleSessionChange} />
}

export default App
