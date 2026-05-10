import { create } from 'zustand'
import type {
  ErrorPayload,
  GitEventPayload,
  GraphPayload,
  WSMessage,
} from '../types/protocol'

/**
 * Discriminated union для рендеру у терміналі / списку подій.
 * Зберігаємо у state у хронологічному порядку.
 */
export type ChatEvent =
  | {
      id: string
      kind: 'git'
      timestamp: number
      userId?: string
      action?: string
      command: string
      argv: string[]
      exitCode: number
      stdout: string
      stderr: string
    }
  | {
      id: string
      kind: 'user-join'
      timestamp: number
      userId: string
      username?: string
    }
  | {
      id: string
      kind: 'user-leave'
      timestamp: number
      userId: string
    }
  | {
      id: string
      kind: 'error'
      timestamp: number
      reason: string
      detail?: string
    }

export interface User {
  id: string
  username?: string
}

interface GitState {
  graph: GraphPayload
  events: ChatEvent[]
  users: Record<string, User>
  applyMessage: (msg: WSMessage) => void
  reset: () => void
}

const EMPTY_GRAPH: GraphPayload = { nodes: [], edges: [] }

let eventCounter = 0
const nextEventId = (): string => {
  eventCounter += 1
  return `evt-${Date.now()}-${eventCounter}`
}

/**
 * Single source of truth для UI:
 *   * `graph` — повністю замінюється кожним GRAPH_UPDATE (immutable swap).
 *   * `events` — append-only список (старі залишаються; обрізку зробимо
 *      в Phase 4.6 якщо знадобиться, поки навантаження мінімальне).
 *   * `users` — плоска map id → username. USER_LEFT видаляє запис.
 */
export const useGitStore = create<GitState>((set) => ({
  graph: EMPTY_GRAPH,
  events: [],
  users: {},

  applyMessage: (msg) => {
    switch (msg.type) {
      case 'GRAPH_UPDATE': {
        if (msg.graph) set({ graph: msg.graph })
        return
      }

      case 'USER_JOINED': {
        if (!msg.userId) return
        const userId = msg.userId
        const username = msg.username ?? undefined
        set((s) => ({
          users: { ...s.users, [userId]: { id: userId, username } },
          events: [
            ...s.events,
            {
              id: nextEventId(),
              kind: 'user-join',
              timestamp: Date.now(),
              userId,
              username,
            },
          ],
        }))
        return
      }

      case 'USER_LEFT': {
        if (!msg.userId) return
        const userId = msg.userId
        set((s) => {
          const nextUsers = { ...s.users }
          delete nextUsers[userId]
          return {
            users: nextUsers,
            events: [
              ...s.events,
              {
                id: nextEventId(),
                kind: 'user-leave',
                timestamp: Date.now(),
                userId,
              },
            ],
          }
        })
        return
      }

      case 'GIT_EVENT': {
        const payload = (msg.payload ?? {}) as Partial<GitEventPayload>
        set((s) => ({
          events: [
            ...s.events,
            {
              id: nextEventId(),
              kind: 'git',
              timestamp: Date.now(),
              userId: msg.userId ?? undefined,
              action: msg.action ?? undefined,
              command: payload.command ?? '',
              argv: payload.argv ?? [],
              exitCode: payload.exit_code ?? 0,
              stdout: payload.stdout ?? '',
              stderr: payload.stderr ?? '',
            },
          ],
        }))
        return
      }

      case 'ERROR': {
        const payload = (msg.payload ?? {}) as Partial<ErrorPayload>
        set((s) => ({
          events: [
            ...s.events,
            {
              id: nextEventId(),
              kind: 'error',
              timestamp: Date.now(),
              reason: payload.reason ?? 'unknown',
              detail: payload.detail,
            },
          ],
        }))
        return
      }

      default: {
        // GIT_COMMAND — outbound, від сервера прийти не має.
        console.warn('ws.unhandled_message_type', msg.type, msg)
      }
    }
  },

  reset: () => set({ graph: EMPTY_GRAPH, events: [], users: {} }),
}))
