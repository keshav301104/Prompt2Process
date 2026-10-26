import { useId } from 'react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipContentProps } from 'recharts'
import { humanize, num } from '../lib/format'

/* ------------------------------------------------------------------ sparkline (plain SVG) */
export function Sparkline({ values, color = 'var(--accent)', height = 28 }: { values: number[]; color?: string; height?: number }) {
  const id = useId()
  const w = 120
  const v = values.length > 1 ? values : [0, ...(values.length ? values : [0])]
  const max = Math.max(...v, 1)
  const pts = v.map((y, i) => [(i / (v.length - 1)) * w, height - 2 - (y / max) * (height - 4)] as const)
  const line = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  return (
    <svg viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" className="h-7 w-full overflow-visible" aria-hidden>
      <defs>
        <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity="0.28" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${line} L${w},${height} L0,${height} Z`} fill={`url(#${id})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="1.5" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  )
}

/* ------------------------------------------------------------------ shared chart chrome */
const axis = { stroke: 'var(--fg-subtle)', fontSize: 11, tickLine: false, axisLine: false } as const

function ChartTip({ active, payload, label, fmtLabel }: Partial<TooltipContentProps<number, string>> & { fmtLabel?: (l: unknown) => string }) {
  if (!active || !payload?.length) return null
  return (
    <div className="min-w-36 rounded-md border border-line-strong bg-panel px-2.5 py-2 text-xs shadow-pop">
      {label != null && <div className="mb-1 font-medium text-fg">{fmtLabel ? fmtLabel(label) : String(label)}</div>}
      {payload.filter((p) => Number(p.value) > 0 || payload.length === 1).map((p) => (
        <div key={String(p.dataKey)} className="flex items-center gap-2 text-muted">
          <span className="size-2 rounded-sm" style={{ background: p.color }} />
          <span className="flex-1">{p.name}</span>
          <span className="font-medium text-fg tnum">{num(Number(p.value), 1)}</span>
        </div>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------------ outcomes by sector (stacked) */
export const OUTCOME_SERIES = [
  { key: 'done', label: 'Done', color: 'var(--ok)' },
  { key: 'waiting', label: 'Awaiting approval', color: 'var(--accent)' },
  { key: 'review', label: 'Needs review', color: 'var(--warn)' },
  { key: 'stopped', label: 'Rejected / failed', color: 'var(--bad)' },
  { key: 'active', label: 'Queued / running', color: 'var(--fg-subtle)' },
] as const
export type OutcomeRow = { sector: string } & Record<(typeof OUTCOME_SERIES)[number]['key'], number>

export function OutcomesBySector({ data }: { data: OutcomeRow[] }) {
  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        {OUTCOME_SERIES.map((s) => (
          <span key={s.key} className="flex items-center gap-1.5"><span className="size-2 rounded-sm" style={{ background: s.color }} />{s.label}</span>
        ))}
      </div>
      <ResponsiveContainer width="100%" height={Math.max(150, data.length * 36 + 24)}>
        <BarChart data={data} layout="vertical" margin={{ left: 0, right: 12, top: 4, bottom: 0 }} barCategoryGap={9}>
          <CartesianGrid horizontal={false} stroke="var(--line)" />
          <XAxis type="number" {...axis} allowDecimals={false} />
          <YAxis type="category" dataKey="sector" {...axis} width={128} tick={{ fill: 'var(--fg-muted)', fontSize: 12 }} />
          <Tooltip cursor={{ fill: 'var(--raised)' }} content={<ChartTip />} />
          {OUTCOME_SERIES.map((s) => (
            <Bar key={s.key} dataKey={s.key} name={s.label} stackId="a" fill={s.color} stroke="var(--panel)" strokeWidth={2} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

/* ------------------------------------------------------------------ issues caught by type */
export function IssuesByType({ data }: { data: Record<string, number> }) {
  const rows = Object.entries(data).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([k, v]) => ({ type: humanize(k), count: v }))
  return (
    <ResponsiveContainer width="100%" height={Math.max(150, rows.length * 28 + 20)}>
      <BarChart data={rows} layout="vertical" margin={{ left: 0, right: 28, top: 0, bottom: 0 }} barCategoryGap={7}>
        <XAxis type="number" hide allowDecimals={false} />
        <YAxis type="category" dataKey="type" {...axis} width={164} tick={{ fill: 'var(--fg-muted)', fontSize: 12 }} />
        <Tooltip cursor={{ fill: 'var(--raised)' }} content={<ChartTip />} />
        <Bar dataKey="count" name="Cases flagged" fill="var(--accent)" radius={[0, 3, 3, 0]} isAnimationActive={false}
          label={{ position: 'right', fill: 'var(--fg-muted)', fontSize: 11 }} />
      </BarChart>
    </ResponsiveContainer>
  )
}

/* ------------------------------------------------------------------ AI calls per task (rolling) */
export function AiCallsTrend({ series }: { series: { task_index: number; ai_calls: number }[] }) {
  const id = useId()
  const data = series.map((p, i) => {
    const win = series.slice(Math.max(0, i - 4), i + 1)
    return { idx: p.task_index, avg: win.reduce((s, x) => s + x.ai_calls, 0) / win.length }
  })
  return (
    <ResponsiveContainer width="100%" height={180}>
      <AreaChart data={data} margin={{ left: -18, right: 8, top: 8, bottom: 0 }}>
        <defs>
          <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="var(--accent)" stopOpacity={0.3} />
            <stop offset="1" stopColor="var(--accent)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} stroke="var(--line)" />
        <XAxis dataKey="idx" {...axis} minTickGap={24} />
        <YAxis {...axis} allowDecimals={false} />
        <Tooltip content={<ChartTip fmtLabel={(l) => `Task #${l}`} />} cursor={{ stroke: 'var(--line-strong)' }} />
        <Area type="monotone" dataKey="avg" name="AI calls / task (5-task avg)" stroke="var(--accent)" strokeWidth={2}
          fill={`url(#${id})`} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--panel)' }} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  )
}
