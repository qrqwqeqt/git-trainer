/**
 * Дзеркало WebSocket-протоколу backend-а (`backend/app/models/schemas.py`).
 *
 * Усі типи мають точно збігатися з тим, що віддає сервер; зміни тут
 * або там потребують одночасного оновлення з обох боків.
 */

export type WSMessageType =
  | 'GIT_EVENT'
  | 'USER_JOINED'
  | 'USER_LEFT'
  | 'GRAPH_UPDATE'
  | 'GIT_COMMAND'
  | 'ERROR'

// ---------- Graph ----------

export interface GraphNode {
  id: string
  label: string | null
  branch: string | null
  parents: string[]
}

export interface GraphEdge {
  source: string
  target: string
}

export interface GraphPayload {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

// ---------- Payloads ----------

/** Що віддає executor у `payload` GIT_EVENT-а. */
export interface GitEventPayload {
  command: string
  argv: string[]
  exit_code: number
  stdout: string
  stderr: string
}

/** Що віддає `_send_error` хендлера — reason обовʼязковий, detail опційний. */
export interface ErrorPayload {
  reason: string
  detail?: string
  received?: string | null
}

// ---------- Generic envelope ----------

/**
 * Універсальний envelope під будь-яку WS-подію. Конкретна форма визначається
 * полем `type`; payload/graph заповнюються у залежності від події.
 */
export interface WSMessage {
  type: WSMessageType
  action?: string | null
  userId?: string | null
  username?: string | null
  payload?: Record<string, unknown> | null
  graph?: GraphPayload | null
  ts?: string  // ISO datetime
}

// ---------- Outbound (client → server) ----------

export interface GitCommandMessage {
  type: 'GIT_COMMAND'
  payload: { command: string }
}
