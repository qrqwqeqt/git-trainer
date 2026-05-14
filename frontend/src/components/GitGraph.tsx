import { useEffect, useMemo } from 'react'
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import dagre from 'dagre'

import type { GraphPayload } from '../types/protocol'
import { useGitStore } from '../store/gitStore'
import './GitGraph.css'

// --------------------------- node renderer ---------------------------

interface CommitNodeData extends Record<string, unknown> {
  sha: string
  label: string
  branch: string | null
}

type CommitNodeType = Node<CommitNodeData, 'commit'>

function CommitNode({ data }: NodeProps<CommitNodeType>) {
  // Layout: дитячі коміти зверху, parent — знизу (dagre setEdge child→parent
  // у TB напрямку). Тому source (parent) має «дивитися» вгору, а target
  // (child) — вниз: edge тоді йде природно знизу-вверх без петель.
  return (
    <div className="commit-node">
      <Handle type="target" position={Position.Bottom} isConnectable={false} />
      <div className="commit-node__sha">{data.sha.slice(0, 7)}</div>
      <div className="commit-node__label" title={data.label}>
        {data.label || '(no message)'}
      </div>
      {data.branch && (
        <div className="commit-node__branch">{data.branch}</div>
      )}
      <Handle type="source" position={Position.Top} isConnectable={false} />
    </div>
  )
}

const nodeTypes = { commit: CommitNode }

// --------------------------- layout (dagre) ---------------------------

const NODE_WIDTH = 180
const NODE_HEIGHT = 78

function layoutGraph(
  graph: GraphPayload,
): { nodes: CommitNodeType[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'TB', nodesep: 32, ranksep: 56 })
  g.setDefaultEdgeLabel(() => ({}))

  for (const n of graph.nodes) {
    g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT })
  }
  for (const e of graph.edges) {
    // У git-i parent старший за child; у dagre напрямок задає, як layout-ити
    // ярус. Робимо edge child→parent у layout, але рендерити будемо
    // parent→child візуально (нижче new edges).
    g.setEdge(e.target, e.source)
  }
  dagre.layout(g)

  const nodes: CommitNodeType[] = graph.nodes.map((n) => {
    const pos = g.node(n.id)
    return {
      id: n.id,
      type: 'commit',
      position: {
        x: (pos?.x ?? 0) - NODE_WIDTH / 2,
        y: (pos?.y ?? 0) - NODE_HEIGHT / 2,
      },
      data: {
        sha: n.id,
        label: n.label ?? '',
        branch: n.branch,
      },
    }
  })

  const edges: Edge[] = graph.edges.map((e) => ({
    id: `${e.source}->${e.target}`,
    source: e.source,
    target: e.target,
    type: 'smoothstep',
    animated: false,
  }))

  return { nodes, edges }
}

// --------------------------- inner component ---------------------------

function GitGraphInner() {
  const graph = useGitStore((s) => s.graph)
  const { nodes, edges } = useMemo(() => layoutGraph(graph), [graph])
  const { fitView } = useReactFlow()
  const nodeCount = nodes.length

  // fitView лише при зміні кількості нод — щоб не «стрибати» при додаванні
  // лейблів гілок без додавання коммітів. Анімація 250 мс — м’яко.
  useEffect(() => {
    if (nodeCount === 0) return
    const handle = window.setTimeout(() => {
      fitView({ duration: 250, padding: 0.25 })
    }, 0)
    return () => window.clearTimeout(handle)
  }, [nodeCount, fitView])

  if (nodeCount === 0) {
    return (
      <div className="git-graph git-graph--empty">
        Граф порожній — введи у термінал <code>git init</code>, додай файл і
        зроби <code>git commit</code>.
      </div>
    )
  }

  return (
    <div className="git-graph">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.25 }}
        nodesDraggable={false}
        nodesConnectable={false}
        edgesFocusable={false}
        elementsSelectable={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={16} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}

// --------------------------- export ---------------------------

export function GitGraph() {
  return (
    <ReactFlowProvider>
      <GitGraphInner />
    </ReactFlowProvider>
  )
}
