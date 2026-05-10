import { useMemo } from 'react'

import { Room } from './components/Room'
import { readSessionFromUrl } from './lib/session'

function App() {
  // Сесія читається один раз з URL/localStorage; зміна ?room=... буде
  // підхоплена тільки при reload — для MVP цього достатньо.
  const session = useMemo(() => readSessionFromUrl(), [])
  return <Room session={session} />
}

export default App
