import { useEffect, useMemo, useRef } from 'react'
import { Background, Controls, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps, type ReactFlowInstance } from '@xyflow/react'
import { CheckCircle2, GitBranch, IndianRupee, RotateCw, ShieldCheck, Send, XCircle } from 'lucide-react'
import type { CheckReport, Plan, Step } from '../lib/api'
import { cn, MONEY_ACTIONS } from '../lib/format'
import { Pill } from './ui'

const W = 256
const GAP_Y = 30
const GAP_X = 28
const ROUTE_RE = /^\s*\w+\.route\s*==\s*'([^']+)'/

type StepData = { step: Step; selected: boolean; edited: boolean; error: boolean; branch?: string }
type StepNodeT = Node<StepData, 'step'>

const nodeHeight = (s: Step) =>
  26 + 16 + Math.ceil(s.title.length / 34) * 19 + (s.when ? 30 : 0) + (badges(s).length ? 28 : 0)

const badges = (s: Step) => [
  s.requires_approval && 'approval',
  MONEY_ACTIONS.has(s.action) && 'money',
  s.side_effect && 'side',
  (s.on_error.retry > 1 || !!s.on_error.fallback) && 'retry',
].filter(Boolean) as string[]

/** Lays the plan out top→bottom; consecutive steps guarded by `route == 'x'` become parallel lanes. */
function layout(plan: Plan, sel: string | null, edited: Set<string>, errors: Set<string>) {
  type Block = { kind: 'main'; step: Step } | { kind: 'branch'; lanes: { key: string; steps: Step[] }[] }
  const blocks: Block[] = []
  for (const s of plan.steps) {
    const m = s.when?.match(ROUTE_RE)
    const last = blocks[blocks.length - 1]
    if (!m) blocks.push({ kind: 'main', step: s })
    else if (last?.kind === 'branch') {
      const lane = last.lanes.find((l) => l.key === m[1])
      if (lane) lane.steps.push(s)
      else last.lanes.push({ key: m[1], steps: [s] })
    } else blocks.push({ kind: 'branch', lanes: [{ key: m[1], steps: [s] }] })
  }
  const nodes: StepNodeT[] = []
  const edges: Edge[] = []
  let y = 0
  let exits: string[] = []
  const mk = (s: Step, x: number, yy: number, branch?: string) =>
    nodes.push({ id: s.id, type: 'step', position: { x, y: yy }, data: { step: s, selected: sel === s.id, edited: edited.has(s.id), error: errors.has(s.id), branch } })
  const link = (from: string, to: string, label?: string, faint?: boolean) =>
    edges.push({ id: `${from}-${to}`, source: from, target: to, type: 'smoothstep', label,
      style: faint ? { strokeDasharray: '4 4', opacity: 0.6 } : undefined })
  for (const b of blocks) {
    if (b.kind === 'main') {
      mk(b.step, -W / 2, y)
      exits.forEach((e) => link(e, b.step.id, undefined, exits.length > 1))
      exits = [b.step.id]
      y += nodeHeight(b.step) + GAP_Y
    } else {
      const n = b.lanes.length
      let tallest = 0
      const next: string[] = []
      b.lanes.forEach((lane, i) => {
        const x = (i - (n - 1) / 2) * (W + GAP_X) - W / 2
        let ly = y + 14
        lane.steps.forEach((s, j) => {
          mk(s, x, ly, j === 0 ? lane.key : undefined)
          if (j === 0) exits.forEach((e) => link(e, s.id, lane.key))
          else link(lane.steps[j - 1].id, s.id)
          ly += nodeHeight(s) + GAP_Y
        })
        tallest = Math.max(tallest, ly - y)
        next.push(lane.steps[lane.steps.length - 1].id)
      })
      exits = next
      y += tallest + 6
    }
  }
  const xs = nodes.map((n) => n.position.x)
  return { nodes, edges, minX: Math.min(...xs, -W / 2), maxX: Math.max(...xs, -W / 2) + W }
}

function StepNode({ data }: NodeProps<StepNodeT>) {
  const { step: s, selected, edited, error } = data
  const b = badges(s)
  return (
    <div className={cn('relative rounded-lg border bg-panel px-3 py-2.5 shadow-[0_1px_2px_rgb(0_0_0/0.12)] transition-shadow',
      s.when ? 'border-dashed border-line-strong' : 'border-line-strong',
      selected && 'border-solid border-accent ring-2 ring-accent/30', error && 'border-solid border-bad ring-2 ring-bad/25')}
      style={{ width: W }}>
      <Handle type="target" position={Position.Top} />
      <div className="flex items-center gap-1.5 font-mono text-2xs">
        <span className="rounded bg-raised px-1 text-muted">{s.id}</span>
        <span className="truncate text-subtle">{s.action}</span>
        {edited && <span className="ml-auto flex items-center gap-1 text-accent"><span className="size-1.5 rounded-full bg-accent" />edited</span>}
      </div>
      <div className="mt-1 text-sm leading-[19px] font-medium text-fg">{s.title}</div>
      {s.when && (
        <div className="mt-2 flex items-center gap-1.5 truncate rounded border border-line bg-sunken px-1.5 py-0.5 font-mono text-2xs text-muted" title={s.when}>
          <GitBranch className="size-3 shrink-0 text-accent" /><span className="text-accent">if</span><span className="truncate">{s.when}</span>
        </div>
      )}
      {b.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {b.includes('approval') && <Pill tone="accent" icon={ShieldCheck}>Approval</Pill>}
          {b.includes('money') && <Pill tone="warn" icon={IndianRupee}>Moves money</Pill>}
          {b.includes('side') && !b.includes('money') && <Pill icon={Send}>Side effect</Pill>}
          {b.includes('retry') && <Pill icon={RotateCw}>Retry ×{s.on_error.retry}{s.on_error.fallback ? ` → ${s.on_error.fallback}` : ''}</Pill>}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}
const nodeTypes = { step: StepNode }

export function PlanGraph({ plan, selected = null, onSelect, edited, errors, className }: {
  plan: Plan; selected?: string | null; onSelect?: (id: string | null) => void; edited?: Set<string>; errors?: Set<string>; className?: string
}) {
  const box = useRef<HTMLDivElement>(null)
  const flow = useRef<ReactFlowInstance<StepNodeT> | null>(null)
  const g = useMemo(() => layout(plan, selected, edited ?? new Set(), errors ?? new Set()), [plan, selected, edited, errors])
  useEffect(() => { // bring a selected step into view if it is off-screen
    const n = g.nodes.find((x) => x.id === selected)
    if (!flow.current || !n || !box.current) return
    const { x, y, zoom } = flow.current.getViewport()
    const sx = n.position.x * zoom + x
    const sy = n.position.y * zoom + y
    if (sx < 0 || sy < 0 || sx + W * zoom > box.current.clientWidth || sy + 100 * zoom > box.current.clientHeight)
      void flow.current.setCenter(n.position.x + W / 2, n.position.y + 60, { zoom, duration: 300 })
  }, [selected, g.nodes])
  const fit = (inst: ReactFlowInstance<StepNodeT>) => {
    flow.current = inst
    const w = box.current?.clientWidth ?? 800
    const zoom = Math.max(0.85, Math.min(1, (w - 48) / (g.maxX - g.minX)))
    void inst.setViewport({ x: w / 2 - ((g.minX + g.maxX) / 2) * zoom, y: 28, zoom })
  }
  return (
    <div ref={box} className={cn('h-full w-full', className)}>
      <ReactFlow<StepNodeT> nodes={g.nodes} edges={g.edges} nodeTypes={nodeTypes} onInit={fit}
        onNodeClick={(_, n) => onSelect?.(n.id)} onPaneClick={() => onSelect?.(null)}
        nodesDraggable={false} nodesConnectable={false} elementsSelectable={!!onSelect} panOnScroll zoomOnScroll={false}
        minZoom={0.3} maxZoom={1.5}>
        <Background gap={18} size={1} />
        <Controls showInteractive={false} position="bottom-right" fitViewOptions={{ padding: 0.08 }} />
      </ReactFlow>
    </div>
  )
}

/** Step ids mentioned by check errors, e.g. "[s14] …". */
export const stepsWithErrors = (r?: CheckReport | null) =>
  new Set((r?.errors ?? []).flatMap((e) => [...e.matchAll(/\[(\w+)\]/g)].map((m) => m[1])))

export function CheckReportView({ report, compact }: { report: CheckReport; compact?: boolean }) {
  const passed = report.checks.filter((c) => c.passed).length
  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <span className="text-sm font-medium">Compiler checks</span>
        <Pill tone={report.ok ? 'ok' : 'bad'} icon={report.ok ? CheckCircle2 : XCircle}>{passed}/{report.checks.length} passed</Pill>
      </div>
      <ul className={cn('grid gap-px overflow-hidden rounded-md border border-line bg-line', !compact && 'sm:grid-cols-2')}>
        {report.checks.map((c) => (
          <li key={c.id} className="bg-panel px-2.5 py-2">
            <div className="flex items-center gap-2 text-sm">
              {c.passed ? <CheckCircle2 className="size-3.5 shrink-0 text-ok" /> : <XCircle className="size-3.5 shrink-0 text-bad" />}
              <span className={cn(!c.passed && 'font-medium text-bad')}>{c.name}</span>
            </div>
            {c.details.map((d) => <p key={d} className="mt-1 pl-5.5 font-mono text-2xs leading-4 text-muted">{d}</p>)}
          </li>
        ))}
      </ul>
      {report.warnings.length > 0 && (
        <ul className="mt-2 space-y-1">{report.warnings.map((w) => <li key={w} className="text-xs text-warn">⚠ {w}</li>)}</ul>
      )}
    </div>
  )
}
