import { useCallback, useState } from 'react'

import { Room } from './components/Room'
import {
  readSessionFromUrl,
  saveUsername,
  updateUrlForSession,
  type SessionInfo,
} from './lib/session'

function App() {
  const [session, setSession] = useState<SessionInfo>(() => readSessionFromUrl())

  const handleSessionChange = useCallback((next: SessionInfo) => {
    saveUsername(next.username)
    updateUrlForSession(next)
    setSession(next)
  }, [])

  return <Room session={session} onSessionChange={handleSessionChange} />
}

export default App
