import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type KeyboardEvent,
} from 'react'
// useEffect лишається у Room для reset() при зміні roomId

import { useWebSocket, type ConnectionState } from '../hooks/useWebSocket'
import { resetSandbox } from '../lib/api'
import {
  buildRoomWsUrl,
  sanitizeSlug,
  sanitizeUsername,
  type SessionInfo,
} from '../lib/session'
import { useGitStore } from '../store/gitStore'
import { GitGraph } from './GitGraph'
import { Terminal } from './Terminal'
import './Room.css'

export interface RoomProps {
  session: SessionInfo
  onSessionChange: (next: SessionInfo) => void
}

const STATE_LABEL: Record<ConnectionState, string> = {
  connecting: 'підключаюсь',
  open: 'онлайн',
  closed: 'відключено',
  error: 'помилка',
}

export function Room({ session, onSessionChange }: RoomProps) {
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

  const [resetting, setResetting] = useState(false)
  const handleReset = useCallback(async () => {
    if (resetting) return
    setResetting(true)
    try {
      await resetSandbox(session.roomId)
      reset()
    } catch (err) {
      console.error('reset failed', err)
    } finally {
      setResetting(false)
    }
  }, [resetting, session.roomId, reset])

  const [copied, setCopied] = useState(false)
  const handleCopyLink = useCallback(async () => {
    // Копіюємо тільки room — не username. Так одержувач відкриває
    // лендинг і вводить свій нік, а не приходить як «ти».
    const link = `${window.location.origin}/?room=${encodeURIComponent(session.roomId)}`
    try {
      await navigator.clipboard.writeText(link)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch (err) {
      console.error('copy failed', err)
    }
  }, [session.roomId])

  const userList = Object.values(users)

  return (
    <div className="room">
      <header className="room__header">
        <div className="room__brand">
          <img
            src="/logo.svg"
            alt="Git Trainer"
            className="room__logo"
            width={67}
            height={36}
          />
          <strong>Git Trainer</strong>
        </div>

        <div className="room__inputs">
          <EditableField
            // key — щоб зміна сесії ззовні (commit) перестворила input
            // зі свіжим draft-станом, без setState-in-effect.
            key={`room-${session.roomId}`}
            label="кімната"
            value={session.roomId}
            sanitize={sanitizeSlug}
            onCommit={(v) =>
              onSessionChange({ ...session, roomId: v || 'demo' })
            }
          />
          <EditableField
            key={`user-${session.username}`}
            label="ти"
            value={session.username}
            sanitize={sanitizeUsername}
            onCommit={(v) =>
              onSessionChange({ ...session, username: v || 'guest' })
            }
          />
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

        <button
          type="button"
          className={`room__share${copied ? ' room__share--copied' : ''}`}
          onClick={handleCopyLink}
          title="Скопіювати посилання на кімнату"
        >
          {copied ? <CheckIcon /> : <LinkIcon />}
          <span>{copied ? 'скопійовано' : 'копіювати лінк'}</span>
        </button>

        <button
          type="button"
          className="room__reset"
          onClick={handleReset}
          disabled={resetting}
          title="Скинути sandbox-контейнер кімнати (видалити репозиторій)"
        >
          {resetting ? 'скидаю…' : '↻ reset'}
        </button>

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

// --------------------------- icons ---------------------------

function LinkIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width={14}
      height={14}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M10 14a5 5 0 0 0 7.07 0l3-3a5 5 0 0 0-7.07-7.07l-1.5 1.5" />
      <path d="M14 10a5 5 0 0 0-7.07 0l-3 3a5 5 0 0 0 7.07 7.07l1.5-1.5" />
    </svg>
  )
}

function CheckIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width={14}
      height={14}
      fill="none"
      stroke="currentColor"
      strokeWidth={2.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M5 12.5l4.5 4.5L19 7" />
    </svg>
  )
}

// --------------------------- editable field ---------------------------

interface EditableFieldProps {
  label: string
  value: string
  sanitize: (raw: string) => string
  onCommit: (next: string) => void
}

function EditableField({
  label,
  value,
  sanitize,
  onCommit,
}: EditableFieldProps) {
  // Local-only draft. Зміни value ззовні підхопить key-remount у Room.
  const [draft, setDraft] = useState(value)

  const commit = () => {
    const next = sanitize(draft)
    if (next && next !== value) onCommit(next)
    else setDraft(value) // повертаємо, якщо ввели сміття
  }

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.currentTarget.blur()
    } else if (e.key === 'Escape') {
      setDraft(value)
      e.currentTarget.blur()
    }
  }

  return (
    <label className="room__field">
      <span className="room__field-label">{label}:</span>
      <input
        className="room__field-input"
        value={draft}
        spellCheck={false}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={onKeyDown}
      />
    </label>
  )
}
