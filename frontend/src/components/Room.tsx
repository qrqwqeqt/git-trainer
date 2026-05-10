import { useCallback, useEffect, useMemo } from 'react'

import { useWebSocket, type ConnectionState } from '../hooks/useWebSocket'
import { buildRoomWsUrl, type SessionInfo } from '../lib/session'
import { useGitStore } from '../store/gitStore'
import { GitGraph } from './GitGraph'
import { Terminal } from './Terminal'
import './Room.css'

export interface RoomProps {
  session: SessionInfo
}

const STATE_LABEL: Record<ConnectionState, string> = {
  connecting: '🟡 підключаюсь',
  open: '🟢 онлайн',
  closed: '🔴 відключено',
  error: '🔴 помилка',
}

export function Room({ session }: RoomProps) {
  const wsUrl = useMemo(() => buildRoomWsUrl(session), [session])
  const applyMessage = useGitStore((s) => s.applyMessage)
  const reset = useGitStore((s) => s.reset)
  const users = useGitStore((s) => s.users)

  // Чистимо стан при зміні кімнати — щоб у нову кімнату не «потекли»
  // події попередньої. Перший mount теж проходить через reset.
  useEffect(() => {
    reset()
  }, [reset, session.roomId])

  const { state, sendMessage } = useWebSocket({
    url: wsUrl,
    onMessage: applyMessage,
  })

  const handleCommand = useCallback(
    (command: string) => {
      sendMessage({ type: 'GIT_COMMAND', payload: { command } })
    },
    [sendMessage],
  )

  const userList = Object.values(users)

  return (
    <div className="room">
      <header className="room__header">
        <div className="room__brand">
          <span className="room__logo">⎇</span>
          <strong>Git Trainer</strong>
        </div>
        <div className="room__meta">
          <span>
            кімната: <code>{session.roomId}</code>
          </span>
          <span>
            ти: <code>{session.username}</code>
          </span>
        </div>
        <div className="room__users" title="Учасники в кімнаті">
          {userList.length === 0 ? (
            <span className="room__users-empty">— нікого —</span>
          ) : (
            userList.map((u) => (
              <span key={u.id} className="room__user-chip">
                {u.username ?? u.id}
              </span>
            ))
          )}
        </div>
        <span className={`room__state room__state--${state}`}>
          {STATE_LABEL[state]}
        </span>
      </header>

      <main className="room__main">
        <section className="room__panel room__panel--terminal">
          <h2 className="room__panel-title">Термінал</h2>
          <div className="room__panel-body">
            <Terminal onCommand={handleCommand} />
          </div>
        </section>
        <section className="room__panel room__panel--graph">
          <h2 className="room__panel-title">Граф гілок</h2>
          <div className="room__panel-body">
            <GitGraph />
          </div>
        </section>
      </main>
    </div>
  )
}
