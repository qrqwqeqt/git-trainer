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
const HISTORY_LIMIT = 200

// xterm присилає одно-байтові escape-коди для Ctrl-комбінацій:
const KEY = {
  CTRL_A: 1,
  CTRL_C: 3,
  CTRL_E: 5,
  CTRL_K: 11,
  CTRL_L: 12,
  CTRL_U: 21,
  CTRL_W: 23,
  ENTER: 13,
  BACKSPACE: 127,
  ESC: 27,
}

const ANSI = {
  reset: '[0m',
  dim: '[2m',
  undim: '[22m',
  cyan: '[36m',
  red: '[31m',
  green: '[32m',
  yellow: '[33m',
}

/** Перерисувати рядок prompt-а: clear → prompt + buffer → курсор у позиції. */
function redrawInput(term: XTerm, buffer: string, cursorPos: number): void {
  term.write('\r[K' + PROMPT + buffer)
  const moveBack = buffer.length - cursorPos
  if (moveBack > 0) term.write(`[${moveBack}D`)
}

/**
 * Псевдо-термінал на xterm.js з bash-подібними скороченнями:
 *
 *   Enter            — відправити команду
 *   Backspace/Delete — стерти символ
 *   ← → Home End     — пересувати курсор (Ctrl+A/E теж працює)
 *   ↑ ↓              — історія команд (до HISTORY_LIMIT записів)
 *   Ctrl+U / Ctrl+K  — стерти до початку / до кінця рядка
 *   Ctrl+W           — стерти слово перед курсором
 *   Ctrl+L           — очистити екран
 *   Ctrl+C           — скинути поточний ввід
 */
export function Terminal({ onCommand }: TerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const termRef = useRef<XTerm | null>(null)
  const onCommandRef = useRef(onCommand)
  const seenEventsRef = useRef(0)

  // Стан рядка вводу
  const inputBufferRef = useRef('')
  const cursorPosRef = useRef(0)

  // Історія
  const historyRef = useRef<string[]>([])
  const historyIndexRef = useRef<number | null>(null)
  const draftBufferRef = useRef('') // буфер до початку навігації

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
      /* контейнер ще без розмірів — ResizeObserver зробить fit пізніше. */
    }
    termRef.current = term

    // Replay подій, що могли надійти до mount-а.
    const initial = useGitStore.getState().events
    for (const ev of initial) renderEventLines(term, ev)
    seenEventsRef.current = initial.length

    term.write(
      `Git Trainer — ${ANSI.dim}Enter${ANSI.reset} відправити, ` +
        `${ANSI.dim}↑↓${ANSI.reset} історія, ` +
        `${ANSI.dim}Ctrl+L${ANSI.reset} очистити.\r\n`,
    )
    term.write(PROMPT)

    const dataDisp = term.onData((data) => {
      const buf = inputBufferRef.current
      const pos = cursorPosRef.current
      const code = data.length === 1 ? data.charCodeAt(0) : -1

      // --------------------- однобайтові коди ---------------------

      if (code === KEY.ENTER) {
        const cmd = buf.trim()
        term.write('\r\n')
        if (cmd) {
          const h = historyRef.current
          if (h.length === 0 || h[h.length - 1] !== cmd) {
            h.push(cmd)
            if (h.length > HISTORY_LIMIT) h.shift()
          }
          historyIndexRef.current = null
          draftBufferRef.current = ''
          inputBufferRef.current = ''
          cursorPosRef.current = 0
          onCommandRef.current(cmd)
          // prompt прийде з GIT_EVENT від сервера
        } else {
          inputBufferRef.current = ''
          cursorPosRef.current = 0
          term.write(PROMPT)
        }
        return
      }

      if (code === KEY.CTRL_C) {
        term.write('^C\r\n')
        inputBufferRef.current = ''
        cursorPosRef.current = 0
        historyIndexRef.current = null
        term.write(PROMPT)
        return
      }

      if (code === KEY.BACKSPACE) {
        if (pos > 0) {
          inputBufferRef.current = buf.slice(0, pos - 1) + buf.slice(pos)
          cursorPosRef.current = pos - 1
          redrawInput(term, inputBufferRef.current, cursorPosRef.current)
        }
        return
      }

      if (code === KEY.CTRL_A) {
        if (pos > 0) {
          term.write(`[${pos}D`)
          cursorPosRef.current = 0
        }
        return
      }

      if (code === KEY.CTRL_E) {
        const delta = buf.length - pos
        if (delta > 0) {
          term.write(`[${delta}C`)
          cursorPosRef.current = buf.length
        }
        return
      }

      if (code === KEY.CTRL_U) {
        if (pos > 0) {
          inputBufferRef.current = buf.slice(pos)
          cursorPosRef.current = 0
          redrawInput(term, inputBufferRef.current, 0)
        }
        return
      }

      if (code === KEY.CTRL_K) {
        if (pos < buf.length) {
          inputBufferRef.current = buf.slice(0, pos)
          redrawInput(term, inputBufferRef.current, cursorPosRef.current)
        }
        return
      }

      if (code === KEY.CTRL_W) {
        if (pos > 0) {
          let i = pos
          while (i > 0 && buf[i - 1] === ' ') i -= 1
          while (i > 0 && buf[i - 1] !== ' ') i -= 1
          inputBufferRef.current = buf.slice(0, i) + buf.slice(pos)
          cursorPosRef.current = i
          redrawInput(term, inputBufferRef.current, cursorPosRef.current)
        }
        return
      }

      if (code === KEY.CTRL_L) {
        term.clear()
        redrawInput(term, buf, pos)
        return
      }

      // --------------------- escape-послідовності ---------------------

      if (data.charCodeAt(0) === KEY.ESC && data.length >= 2) {
        const seq = data.slice(1)

        // Up — '[A' (cursor mode) або 'OA' (application mode)
        if (seq === '[A' || seq === 'OA') {
          const h = historyRef.current
          if (h.length === 0) return
          const cur = historyIndexRef.current
          if (cur === null) {
            draftBufferRef.current = buf
            historyIndexRef.current = h.length - 1
          } else if (cur > 0) {
            historyIndexRef.current = cur - 1
          } else {
            return
          }
          const cmd = h[historyIndexRef.current]
          inputBufferRef.current = cmd
          cursorPosRef.current = cmd.length
          redrawInput(term, cmd, cmd.length)
          return
        }

        // Down — '[B' / 'OB'
        if (seq === '[B' || seq === 'OB') {
          const h = historyRef.current
          const cur = historyIndexRef.current
          if (cur === null) return
          let next: string
          if (cur < h.length - 1) {
            historyIndexRef.current = cur + 1
            next = h[historyIndexRef.current]
          } else {
            historyIndexRef.current = null
            next = draftBufferRef.current
          }
          inputBufferRef.current = next
          cursorPosRef.current = next.length
          redrawInput(term, next, next.length)
          return
        }

        // Left — '[D' / 'OD'
        if (seq === '[D' || seq === 'OD') {
          if (pos > 0) {
            cursorPosRef.current = pos - 1
            term.write('[D')
          }
          return
        }

        // Right — '[C' / 'OC'
        if (seq === '[C' || seq === 'OC') {
          if (pos < buf.length) {
            cursorPosRef.current = pos + 1
            term.write('[C')
          }
          return
        }

        // Home — '[H' / 'OH' / '[1~' / '[7~'
        if (seq === '[H' || seq === 'OH' || seq === '[1~' || seq === '[7~') {
          if (pos > 0) {
            term.write(`[${pos}D`)
            cursorPosRef.current = 0
          }
          return
        }

        // End — '[F' / 'OF' / '[4~' / '[8~'
        if (seq === '[F' || seq === 'OF' || seq === '[4~' || seq === '[8~') {
          const delta = buf.length - pos
          if (delta > 0) {
            term.write(`[${delta}C`)
            cursorPosRef.current = buf.length
          }
          return
        }

        // Delete (forward) — '[3~'
        if (seq === '[3~') {
          if (pos < buf.length) {
            inputBufferRef.current = buf.slice(0, pos) + buf.slice(pos + 1)
            redrawInput(term, inputBufferRef.current, cursorPosRef.current)
          }
          return
        }

        // інші escape-послідовності просто ігноруємо
        return
      }

      // --------------------- friкабельні символи ---------------------

      if (data.length === 1 && code >= 32 && code <= 126) {
        inputBufferRef.current = buf.slice(0, pos) + data + buf.slice(pos)
        cursorPosRef.current = pos + 1
        if (pos === buf.length) {
          term.write(data) // швидкий шлях у кінці рядка
        } else {
          redrawInput(term, inputBufferRef.current, cursorPosRef.current)
        }
        return
      }

      // Paste (кілька printable символів за раз)
      if (data.length > 1 && /^[\x20-\x7e]+$/.test(data)) {
        inputBufferRef.current = buf.slice(0, pos) + data + buf.slice(pos)
        cursorPosRef.current = pos + data.length
        redrawInput(term, inputBufferRef.current, cursorPosRef.current)
        return
      }
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
      t.write('\r[K')
      for (const ev of fresh) renderEventLines(t, ev)
      redrawInput(t, inputBufferRef.current, cursorPosRef.current)
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
