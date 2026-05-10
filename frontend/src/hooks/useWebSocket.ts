import { useCallback, useEffect, useRef, useState } from 'react'
import type { WSMessage } from '../types/protocol'

export type ConnectionState = 'connecting' | 'open' | 'closed' | 'error'

export interface UseWebSocketOptions {
  url: string
  onMessage: (msg: WSMessage) => void
  /** Якщо false — hook не підключається (зручно для умовного рендеру). */
  enabled?: boolean
  /** Стеля експоненційного backoff-а в мс. Default 30 сек. */
  maxRetryDelayMs?: number
}

export interface UseWebSocketResult {
  state: ConnectionState
  /**
   * Серіалізує JSON і шле на сервер. Якщо WS не open — повідомлення
   * лягає в чергу й відправляється при наступному успішному підключенні.
   */
  sendMessage: (msg: object) => void
}

/**
 * WebSocket з auto-reconnect-ом.
 *
 *  * onMessage / enabled зчитуються через ref-и, тому їхні зміни
 *    не реконнектять вже відкритий сокет — реконнект буде тільки
 *    при зміні `url` чи `enabled` (якщо переходить у true).
 *  * Backoff: 0.5s → 1s → 2s → ... → maxRetryDelayMs.
 */
export function useWebSocket({
  url,
  onMessage,
  enabled = true,
  maxRetryDelayMs = 30_000,
}: UseWebSocketOptions): UseWebSocketResult {
  const [state, setState] = useState<ConnectionState>('connecting')
  const wsRef = useRef<WebSocket | null>(null)
  const retryRef = useRef(0)
  const onMessageRef = useRef(onMessage)
  const queueRef = useRef<string[]>([])

  // Тримаємо callback-и свіжими, не реконнектячи сокет.
  useEffect(() => {
    onMessageRef.current = onMessage
  }, [onMessage])

  useEffect(() => {
    if (!enabled) return

    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      if (cancelled) return
      setState('connecting')
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        retryRef.current = 0
        setState('open')
        // flush черги, що накопичилась поки сокета не було
        const queued = queueRef.current
        queueRef.current = []
        for (const msg of queued) ws.send(msg)
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as WSMessage
          onMessageRef.current(data)
        } catch (err) {
          console.error('ws.parse_failed', err, event.data)
        }
      }

      ws.onerror = () => {
        setState('error')
      }

      ws.onclose = () => {
        if (wsRef.current === ws) wsRef.current = null
        if (cancelled) return
        setState('closed')
        const delay = Math.min(
          maxRetryDelayMs,
          500 * 2 ** retryRef.current,
        )
        retryRef.current += 1
        timer = setTimeout(connect, delay)
      }
    }

    connect()

    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
      const ws = wsRef.current
      wsRef.current = null
      if (ws) {
        // Уникаємо race: знімаємо обробники, інакше onclose спробує реконект.
        ws.onopen = null
        ws.onmessage = null
        ws.onerror = null
        ws.onclose = null
        ws.close()
      }
    }
  }, [url, enabled, maxRetryDelayMs])

  const sendMessage = useCallback((msg: object) => {
    const json = JSON.stringify(msg)
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(json)
    } else {
      queueRef.current.push(json)
    }
  }, [])

  return { state, sendMessage }
}
