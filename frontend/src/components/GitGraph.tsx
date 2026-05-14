import { useMemo } from 'react'

import type { GraphPayload } from '../types/protocol'
import { useGitStore } from '../store/gitStore'
import './GitGraph.css'

// --------------------------- layout ---------------------------

const LANE_W = 18 // ширина однієї «рейки» (px)
const ROW_H = 28 // висота рядка (px)
const RADIUS = 5 // радіус кружка коміту
const RAIL_STROKE = 1.5 // товщина рейок та зʼєднань

// Палітра lane-ів: cyan, magenta, green, yellow, blue, red — повторюється
// по колу для глибокого графа.
const LANE_COLORS = [
  '#38bdf8',
  '#c084fc',
  '#4ade80',
  '#fbbf24',
  '#60a5fa',
  '#f87171',
] as const

interface PositionedCommit {
  id: string
  label: string
  branch: string | null
  author: string | null
  parents: string[]
  lane: number
  y: number
}

interface CommitLayout {
  commits: PositionedCommit[]
  numLanes: number
}

/**
 * Lane-assignment у дусі `git log --graph`:
 *
 * Йдемо по комітах у тому порядку, як їх віддає backend (newer-first з
 * `git log --all`). У `activeLanes[i]` тримаємо sha коміту, на який «чекає»
 * lane знизу: коли його зустрінемо — займаємо lane і резервуємо parents
 * у вільних/успадкованих lane-ах.
 *
 * Спрощення: перший parent — спадкоємець lane-а коміту (continuation),
 * інші parents (merges) — займають вільні lane-и зліва направо. Це покриває
 * лінійну історію, гілкування й merge — типовий випадок навчальних
 * сценаріїв. Складніші історії (octopus, criss-cross) можуть візуально
 * перетинатися — це OK для MVP.
 */
function computeLayout(graph: GraphPayload): CommitLayout {
  const positioned: PositionedCommit[] = []
  const activeLanes: (string | null)[] = []

  const claim = (sha: string): number => {
    const idx = activeLanes.findIndex((o) => o === sha)
    if (idx !== -1) return idx
    const free = activeLanes.findIndex((o) => o === null)
    if (free !== -1) return free
    activeLanes.push(null)
    return activeLanes.length - 1
  }

  for (const node of graph.nodes) {
    const lane = claim(node.id)
    activeLanes[lane] = null

    // Резервуємо lane-и для parents. Перший — наслідує мою.
    for (let i = 0; i < node.parents.length; i += 1) {
      const p = node.parents[i]
      if (i === 0) {
        activeLanes[lane] = p
      } else {
        const free = activeLanes.findIndex((o) => o === null)
        if (free !== -1) {
          activeLanes[free] = p
        } else {
          activeLanes.push(p)
        }
      }
    }

    positioned.push({
      id: node.id,
      label: node.label ?? '',
      branch: node.branch,
      author: node.author,
      parents: [...node.parents],
      lane,
      y: positioned.length,
    })
  }

  return {
    commits: positioned,
    numLanes: Math.max(1, activeLanes.length),
  }
}

function laneColor(lane: number): string {
  return LANE_COLORS[lane % LANE_COLORS.length]
}

function edgePath(
  childLane: number,
  childY: number,
  parentLane: number,
  parentY: number,
): string {
  const cx = childLane * LANE_W + LANE_W / 2
  const cy = childY * ROW_H + ROW_H / 2
  const px = parentLane * LANE_W + LANE_W / 2
  const py = parentY * ROW_H + ROW_H / 2
  if (childLane === parentLane) {
    return `M${cx} ${cy} L${px} ${py}`
  }
  // Smooth cubic between sibling rows: вертикальні «вусики» згори/знизу,
  // діагональний bezier-перехід посередині.
  const midY = (cy + py) / 2
  return `M${cx} ${cy} C${cx} ${midY},${px} ${midY},${px} ${py}`
}

// --------------------------- component ---------------------------

export function GitGraph() {
  const graph = useGitStore((s) => s.graph)
  const layout = useMemo(() => computeLayout(graph), [graph])

  if (layout.commits.length === 0) {
    return (
      <div className="git-graph git-graph--empty">
        Граф порожній — введи у термінал <code>git init</code>, додай файл і
        зроби <code>git commit</code>.
      </div>
    )
  }

  const railsWidth = layout.numLanes * LANE_W + LANE_W / 2
  const railsHeight = layout.commits.length * ROW_H
  const byId = new Map(layout.commits.map((c) => [c.id, c]))

  return (
    <div className="git-graph">
      <div
        className="git-graph__rows"
        style={{ position: 'relative', minHeight: railsHeight }}
      >
        <svg
          className="git-graph__rails"
          width={railsWidth}
          height={railsHeight}
          aria-hidden="true"
        >
          {/* edges parent → child */}
          {layout.commits.flatMap((c) =>
            c.parents.map((pid) => {
              const parent = byId.get(pid)
              if (!parent) return null
              const color = laneColor(parent.lane)
              return (
                <path
                  key={`${c.id}-${pid}`}
                  d={edgePath(c.lane, c.y, parent.lane, parent.y)}
                  stroke={color}
                  strokeWidth={RAIL_STROKE}
                  fill="none"
                  opacity={0.85}
                />
              )
            }),
          )}
          {/* circles */}
          {layout.commits.map((c) => (
            <circle
              key={c.id}
              cx={c.lane * LANE_W + LANE_W / 2}
              cy={c.y * ROW_H + ROW_H / 2}
              r={RADIUS}
              fill={laneColor(c.lane)}
              stroke="#0b0b0f"
              strokeWidth={2}
            />
          ))}
        </svg>

        <ul
          className="git-graph__commits"
          style={{ paddingLeft: railsWidth }}
        >
          {layout.commits.map((c) => (
            <li
              key={c.id}
              className="commit-row"
              style={{ height: ROW_H }}
              title={tooltipText(c)}
            >
              <span className="commit-row__label">
                {c.label || '(no message)'}
              </span>
              {c.branch && (
                <span
                  className="commit-row__branch"
                  style={{
                    color: laneColor(c.lane),
                    borderColor: laneColor(c.lane),
                  }}
                >
                  {c.branch}
                </span>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function tooltipText(c: PositionedCommit): string {
  const sha = c.id.slice(0, 7)
  const author = c.author ? ` • ${c.author}` : ''
  return `${sha}${author}\n${c.id}`
}
