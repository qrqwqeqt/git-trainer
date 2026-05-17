import { useEffect, useRef, useState, type FormEvent } from 'react'

import {
  generateRoomId,
  getRoomLabel,
  getStoredUsername,
  sanitizeUsername,
} from '../lib/session'
import './Landing.css'

export interface LandingProps {
  /** ?room=... з URL — пред-заповнюємо інпут і дозволяємо join без regenerate. */
  prefillRoom: string | null
  /**
   * Викликається коли користувач натиснув «Увійти / створити».
   * App.tsx уже сам розрулить URL, localStorage і перехід на Room.
   */
  onEnter: (opts: {
    roomId: string
    username: string
    /** Людська назва для збереження у localStorage (опційно). */
    label?: string
  }) => void
}

export function Landing({ prefillRoom, onEnter }: LandingProps) {
  // Якщо прийшли по лінку — підставляємо людську назву (якщо знаємо),
  // інакше — сам roomId. Це дає менш «технічний» вигляд.
  const initialRoom = prefillRoom
    ? getRoomLabel(prefillRoom) ?? prefillRoom
    : ''
  const initialUser = getStoredUsername() ?? ''

  const [roomInput, setRoomInput] = useState(initialRoom)
  const [usernameInput, setUsernameInput] = useState(initialUser)
  const [error, setError] = useState<string | null>(null)

  const roomRef = useRef<HTMLInputElement>(null)
  const userRef = useRef<HTMLInputElement>(null)

  // Фокус: якщо кімната пред-заповнена — на нік, інакше — на кімнату.
  useEffect(() => {
    if (prefillRoom) userRef.current?.focus()
    else roomRef.current?.focus()
  }, [prefillRoom])

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const trimmedRoom = roomInput.trim()
    const trimmedUser = usernameInput.trim()

    if (!trimmedRoom) {
      setError('Введи назву кімнати')
      roomRef.current?.focus()
      return
    }
    if (!trimmedUser) {
      setError('Введи псевдонім')
      userRef.current?.focus()
      return
    }

    const safeUser = sanitizeUsername(trimmedUser)

    // Якщо це join по існуючому лінку (URL дав prefillRoom і користувач
    // не змінив поле) — використовуємо prefillRoom як є, без regenerate.
    // Інакше — це створення нової кімнати: slug + випадковий суфікс.
    const isJoinExisting =
      prefillRoom !== null &&
      (trimmedRoom === prefillRoom || trimmedRoom === getRoomLabel(prefillRoom))

    if (isJoinExisting && prefillRoom) {
      onEnter({ roomId: prefillRoom, username: safeUser })
    } else {
      const roomId = generateRoomId(trimmedRoom)
      onEnter({ roomId, username: safeUser, label: trimmedRoom })
    }
  }

  return (
    <div className="landing">
      <form className="landing__card" onSubmit={handleSubmit} noValidate>
        <img
          src="/logo.svg"
          alt=""
          className="landing__logo"
          width={64}
          height={64}
        />
        <h1 className="landing__title">Git Trainer</h1>
        <p className="landing__subtitle">
          Інтерактивна платформа для навчання Git
        </p>

        <label className="landing__field">
          <span className="landing__label">Псевдонім</span>
          <input
            ref={userRef}
            className="landing__input"
            value={usernameInput}
            spellCheck={false}
            autoComplete="nickname"
            placeholder="напр. dzhe"
            onChange={(e) => {
              setUsernameInput(e.target.value)
              setError(null)
            }}
          />
        </label>

        <label className="landing__field">
          <span className="landing__label">Кімната</span>
          <input
            ref={roomRef}
            className="landing__input"
            value={roomInput}
            spellCheck={false}
            placeholder="напр. react basics"
            onChange={(e) => {
              setRoomInput(e.target.value)
              setError(null)
            }}
          />
        </label>

        {error && <div className="landing__error">{error}</div>}

        <button type="submit" className="landing__submit">
          {prefillRoom ? 'Увійти' : 'Створити кімнату'}
        </button>

        <p className="landing__hint">
          {prefillRoom
            ? 'Ти приєднуєшся до існуючої кімнати за лінком.'
            : 'Назва — для людей. Унікальний ID додасться автоматично.'}
        </p>
      </form>
    </div>
  )
}
