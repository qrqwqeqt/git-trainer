import { useMemo } from 'react'

import type { GraphPayload } from '../types/protocol'
import { useGitStore } from '../store/gitStore'
import './GitGraph.css'

// --------------------------- layout ---------------------------

const LANE_W = 22 // ширина однієї «рейки» (px)
const ROW_H = 30 // висота рядка (px)
const RADIUS = 7 // радіус кружка коміту
const RAIL_STROKE = 1.75 // товщина рейок та зʼєднань
const CIRCLE_STROKE = 2 // товщина обводки кружка

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
 * Lane-assignment за принципом «one branch — one lane».
 *
 * Кроки:
 *  1. Для комітів з decoration (n.branch != null) одразу запамʼятовуємо
 *     їхню гілку.
 *  2. Для решти — успадковуємо гілку від найближчого нащадка (newer-first
 *     порядок з git log гарантує, що нащадок уже мав шанс отримати гілку
 *     перш ніж ми дійшли до батька).
 *  3. main/master завжди отримують lane 0; інші гілки — наступні номери
 *     у порядку появи. Так feature-branch візуально відходить праворуч,
 *     навіть якщо історія по факту лінійна.
 *
 * Це покриває звичні навчальні сценарії: лінійка, гілка від main,
 * merge назад. Складніші історії (octopus, criss-cross) можуть
 * візуально перетинатися — це OK для MVP.
 */
function computeLayout(graph: GraphPayload): CommitLayout {
  const nodes = graph.nodes

  // 1. children map (parent sha → array of child sha)
  const childrenOf = new Map<string, string[]>()
  for (const n of nodes) {
    for (const p of n.parents) {
      const arr = childrenOf.get(p)
      if (arr) arr.push(n.id)
      else childrenOf.set(p, [n.id])
    }
  }

  // 2. визначаємо гілку для кожного коміту
  const commitBranch = new Map<string, string>()
  for (const n of nodes) {
    if (n.branch) commitBranch.set(n.id, n.branch)
  }
  // Successor-inheritance: nodes йдуть newer-first → нащадок уже processed.
  for (const n of nodes) {
    if (commitBranch.has(n.id)) continue
    const kids = childrenOf.get(n.id) ?? []
    for (const cid of kids) {
      const cb = commitBranch.get(cid)
      if (cb) {
        commitBranch.set(n.id, cb)
        break
      }
    }
  }

  // 3. lane number за гілкою (main/master → 0)
  const branchLane = new Map<string, number>([
    ['main', 0],
    ['master', 0],
  ])
  let nextLane = 1
  const laneOf = (branch: string | undefined): number => {
    if (!branch) return 0
    const cached = branchLane.get(branch)
    if (cached !== undefined) return cached
    const lane = nextLane
    branchLane.set(branch, lane)
    nextLane += 1
    return lane
  }

  const positioned: PositionedCommit[] = nodes.map((n, i) => ({
    id: n.id,
    label: n.label ?? '',
    branch: n.branch,
    author: n.author,
    parents: [...n.parents],
    lane: laneOf(commitBranch.get(n.id)),
    y: i,
  }))

  return {
    commits: positioned,
    numLanes: Math.max(1, nextLane),
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
          {/* circles — полі всередині (fill = колір фону панелі), щоб
              кружок виглядав як «вузол» на ребрі, а не як суцільна крапка. */}
          {layout.commits.map((c) => (
            <circle
              key={c.id}
              cx={c.lane * LANE_W + LANE_W / 2}
              cy={c.y * ROW_H + ROW_H / 2}
              r={RADIUS}
              fill="var(--bg-elevated)"
              stroke={laneColor(c.lane)}
              strokeWidth={CIRCLE_STROKE}
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
