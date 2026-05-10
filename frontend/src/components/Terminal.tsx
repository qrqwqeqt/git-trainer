import { useEffect, useRef } from 'react'
import { Terminal as XTerm } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'

import type { ChatEvent } from '../store/gitStore'
import { useGitStore } from '../store/gitStore'
import './Terminal.css'

export interface TerminalProps {
  /** Викликається коли користувач вводить команду й натискає Enter. */
  onCommand: (command: string) => void
}

const PROMPT = '$ '
const ANSI = {
  reset: '\x1b[0m',
  dim: '\x1b[2m',
  undim: '\x1b[22m',
  cyan: '\x1b[36m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
}

/**
 * Псевдо-термінал на xterm.js.
 *
 * UX-нюанси:
 *   * Сам ввід ми накопичуємо у `inputBuffer` поки не приходить '\r' —
 *     тоді шлемо `onCommand(cmd)` і чекаємо на GIT_EVENT, який сам
 *     надрукує prompt $ заново.
 *   * Якщо подія від іншого юзера приходить в момент, коли ти набираєш —
 *     ми очищуємо поточний рядок (`\r\x1b[K`), друкуємо подію та
 *     відновлюємо `$ <твій буфер>`. Курсор лишається у кінці.
 *   * Реконнект / async — через підписку на zustand store. Не зачіпаємо
 *     xterm з-зовні; усі мутації через цей компонент.
 */
export function Terminal({ onCommand }: TerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const termRef = useRef<XTerm | null>(null)
  const inputBufferRef = useRef('')
  const onCommandRef = useRef(onCommand)
  const seenEventsRef = useRef(0)

  // Тримаємо callback свіжим без реконнекту терміналу.
  useEffect(() => {
    onCommandRef.current = onCommand
  }, [onCommand])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const term = new XTerm({
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, "DejaVu Sans Mono", monospace',
      fontSize: 13,
      lineHeight: 1.2,
      cursorBlink: true,
      convertEol: false,
      theme: {
        background: '#1e1e1e',
        foreground: '#e0e0e0',
        cursor: '#e0e0e0',
        cursorAccent: '#1e1e1e',
      },
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(container)
    try {
      fit.fit()
    } catch {
      /* контейнер може бути ще не виміряний — ResizeObserver нижче зробить fit. */
    }
    termRef.current = term

    // Replay подій, що могли накопичитись до mount-а.
    const initial = useGitStore.getState().events
    for (const ev of initial) renderEventLines(term, ev)
    seenEventsRef.current = initial.length

    term.write(
      `Git Trainer — введи команду, напр. ${ANSI.cyan}git status${ANSI.reset}\r\n`,
    )
    term.write(PROMPT)

    const dataDisp = term.onData((data) => {
      const buf = inputBufferRef.current
      if (data === '\r') {
        const cmd = buf.trim()
        term.write('\r\n')
        inputBufferRef.current = ''
        if (cmd) {
          onCommandRef.current(cmd)
          // prompt прийде разом з GIT_EVENT від сервера
        } else {
          term.write(PROMPT)
        }
      } else if (data === '') {
        if (buf.length > 0) {
          inputBufferRef.current = buf.slice(0, -1)
          term.write('\b \b')
        }
      } else if (data === '') {
        term.write('^C\r\n')
        inputBufferRef.current = ''
        term.write(PROMPT)
      } else if (data.length === 1 && data >= ' ') {
        inputBufferRef.current = buf + data
        term.write(data)
      } else if (data.length > 1 && /^[\x20-\x7E]+$/.test(data)) {
        // paste з буфера обміну
        inputBufferRef.current = buf + data
        term.write(data)
      }
      // інші escape-послідовності (стрілки тощо) поки що ігноруємо
    })

    const ro = new ResizeObserver(() => {
      try {
        fit.fit()
      } catch {
        /* контейнер міг від’єднатись */
      }
    })
    ro.observe(container)

    const unsubscribe = useGitStore.subscribe((state) => {
      if (state.events.length <= seenEventsRef.current) return
      const t = termRef.current
      if (!t) return
      const fresh = state.events.slice(seenEventsRef.current)
      seenEventsRef.current = state.events.length
      const currentInput = inputBufferRef.current
      // Очищаємо рядок з prompt+input, друкуємо події, відновлюємо prompt+input.
      t.write('\r\x1b[K')
      for (const ev of fresh) renderEventLines(t, ev)
      t.write(PROMPT + currentInput)
    })

    return () => {
      unsubscribe()
      ro.disconnect()
      dataDisp.dispose()
      term.dispose()
      termRef.current = null
    }
  }, [])

  return <div ref={containerRef} className="terminal" />
}

// --------------------------- event rendering ---------------------------

function renderEventLines(term: XTerm, ev: ChatEvent): void {
  switch (ev.kind) {
    case 'git': {
      const tag = ev.userId ? `${ANSI.dim}[${ev.userId}]${ANSI.undim} ` : ''
      term.write(`${tag}${ANSI.cyan}$ ${ev.command}${ANSI.reset}\r\n`)
      if (ev.stdout) term.write(ev.stdout.replace(/\n/g, '\r\n'))
      if (ev.stderr) {
        term.write(`${ANSI.red}${ev.stderr.replace(/\n/g, '\r\n')}${ANSI.reset}`)
      }
      if (ev.exitCode !== 0) {
        term.write(`${ANSI.yellow}[exit ${ev.exitCode}]${ANSI.reset}\r\n`)
      }
      return
    }
    case 'user-join': {
      const name = ev.username ?? ev.userId
      term.write(`${ANSI.green}→ ${name} приєднався${ANSI.reset}\r\n`)
      return
    }
    case 'user-leave': {
      term.write(`${ANSI.yellow}← ${ev.userId} відключився${ANSI.reset}\r\n`)
      return
    }
    case 'error': {
      const detail = ev.detail ? `: ${ev.detail}` : ''
      term.write(`${ANSI.red}! ${ev.reason}${detail}${ANSI.reset}\r\n`)
      return
    }
  }
}
