import { useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  AlertOctagon, AlertTriangle, CheckCircle2, Circle, CircleDashed, CornerDownRight, FileText, FlaskConical, Hand, Image, Inbox, Info,
  Loader2, Pencil, Play, RotateCw, XCircle, type LucideIcon,
} from 'lucide-react'
import { api, useAction, useEmployee, useLearning, useTask, useTaskEvents, useTemplates, type Field, type Flag, type StepRun, type Task, type Template } from '../lib/api'
import { ago, clock, cn, fieldLabel, humanize, inr, isMoneyField, num, routeLabel, routeTone, sectorMeta } from '../lib/format'
import { Act, Avatar, Button, confidenceTone, Empty, Load, Meter, Mono, Pill, Select, Skeleton, StatusPill, Tabs } from '../components/ui'

export function CasePage() {
  const { id } = useParams()
  const task = useTask(id)
  return (
    <Load q={task} skeleton={<div className="space-y-3 p-6"><Skeleton className="h-10 w-96" /><Skeleton className="h-[70vh]" /></div>}>
      {(t) => (
        <div className="flex h-full flex-col">
          <CaseHeader t={t} />
          <div key={t.id} className="grid min-h-0 flex-1 grid-cols-[minmax(0,5fr)_minmax(0,4fr)_minmax(0,4fr)] divide-x divide-line">
            <DocumentViewer t={t} />
            <FieldsPanel t={t} />
            <RunPanel t={t} />
          </div>
        </div>
      )}
    </Load>
  )
}

function CaseHeader({ t }: { t: Task }) {
  const emp = useEmployee(t.employee_id)
  const templates = useTemplates()
  const run = useAction(() => api.post(`/employees/${t.employee_id}/run`, { task_ids: [t.id] }), { success: 'Case started' })
  const route = t.outcome?.route ?? t.outcome?.final_decision
  const final = t.outcome?.final_decision
  return (
    <div className="border-b border-line bg-panel/40 px-6 py-4">
      <div className="mb-2 text-xs text-subtle"><Link to="/work" className="hover:text-fg">Work queue</Link> / <span className="font-mono">{t.case_id ?? t.id}</span></div>
      <div className="flex items-start gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2.5">
            <h1 className="truncate text-xl font-semibold tracking-tight">{t.title}</h1>
            <StatusPill status={t.status} />
            {t.mode === 'shadow' && <Pill icon={FlaskConical}>Shadow</Pill>}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted">
            {emp.data && <Link to={`/employees/${emp.data.id}`} className="flex items-center gap-1.5 hover:text-fg"><Avatar emp={emp.data} size="sm" />{emp.data.name}</Link>}
            {emp.data && <span className="text-subtle">· {sectorMeta(emp.data.sector).short}</span>}
            <span className="text-subtle">· <Mono className="text-subtle">{t.id}</Mono> · plan v{t.plan_version ?? '—'} · created {ago(t.created_at)} · {t.ai_calls} AI calls{t.duration_s != null ? ` · ${num(t.duration_s, 1)}s` : ''}</span>
          </div>
          {(route || t.outcome?.summary) && (
            <div className="mt-2.5 flex items-center gap-2 text-sm">
              {route && <Pill tone={routeTone(route)}>{routeLabel(route, templates.data)}</Pill>}
              {final && final !== route && !['needs_review', 'failed'].includes(final) && <><span className="text-subtle">→</span><Pill tone={routeTone(final)}>{routeLabel(final, templates.data)}</Pill></>}
              <span className="truncate text-muted">{t.outcome?.summary}</span>
            </div>
          )}
        </div>
        <div className="flex gap-2">
          {(t.status === 'needs_review' || t.status === 'waiting_approval') && <Link to="/inbox"><Button icon={Inbox}>Open in inbox</Button></Link>}
          {t.status === 'queued' && <Act perm="work.run" variant="primary" icon={Play} loading={run.isPending} onClick={() => run.mutate()}>Run case</Act>}
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ documents */
const fileLabel = (p: string) => humanize(p.split('/').pop()!.replace(/\.(pdf|png|jpe?g)$/i, ''))


function DocumentViewer({ t }: { t: Task }) {
  const files = t.files?.length ? t.files : t.file ? [t.file] : []
  const [active, setActive] = useState(files[0] ?? '')
  if (t.kind === 'collection') return <CustomerCard t={t} />
  if (!files.length) return <Empty icon={FileText} title="No document attached" className="h-full" />
  const isImg = /\.(png|jpe?g)$/i.test(active)
  const src = t.files?.length ? `/api/tasks/${t.id}/file?path=${encodeURIComponent(active)}` : `/api/tasks/${t.id}/document`
  return (
    <div className="flex min-h-0 flex-col bg-sunken">
      <div className="flex h-10 shrink-0 items-center gap-1 overflow-x-auto border-b border-line bg-panel px-2">
        {files.map((f) => {
          const Icon = /\.(png|jpe?g)$/i.test(f) ? Image : FileText
          return (
            <button key={f} onClick={() => setActive(f)} className={cn('flex h-7 shrink-0 items-center gap-1.5 rounded-md px-2.5 text-xs',
              f === active ? 'bg-raised font-medium text-fg ring-1 ring-line-strong' : 'text-muted hover:text-fg')}>
              <Icon className="size-3.5" />{t.files?.length ? fileLabel(f) : 'Document'}
            </button>
          )
        })}
        <a href={src} target="_blank" rel="noreferrer" className="ml-auto shrink-0 px-2 text-xs text-subtle hover:text-fg">Open ↗</a>
      </div>
      <div className="min-h-0 flex-1">
        {isImg ? <img src={src} alt={fileLabel(active)} className="h-full w-full object-contain p-4" />
          : <iframe key={src} title={fileLabel(active)} src={`${src}#toolbar=0&navpanes=0&view=FitH`} className="h-full w-full bg-white" />}
      </div>
    </div>
  )
}

function CustomerCard({ t }: { t: Task }) {
  const v = (k: string) => t.fields[k]?.value as string | number | undefined
  return (
    <div className="overflow-y-auto p-5">
      <div className="rounded-lg border border-line bg-panel p-4">
        <div className="text-xs text-subtle">Customer</div>
        <div className="text-base font-semibold">{String(v('customer') ?? '—')}</div>
        <div className="mt-3 grid grid-cols-3 gap-3 text-sm">
          <div><div className="text-xs text-subtle">Amount due</div><div className="font-medium tnum">{inr(Number(v('amount') ?? 0))}</div></div>
          <div><div className="text-xs text-subtle">Days overdue</div><div className="font-medium tnum">{String(v('days_overdue') ?? '—')}</div></div>
          <div><div className="text-xs text-subtle">Language</div><div className="font-medium">{String(v('language') ?? '—')}</div></div>
        </div>
      </div>
      {v('draft_body') != null && (
        <div className="mt-4 rounded-lg border border-line bg-panel">
          <div className="border-b border-line px-4 py-2.5 text-sm font-medium">{String(v('draft_subject') ?? 'Drafted reminder')}</div>
          <p className="px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap">{String(v('draft_body'))}</p>
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ extracted fields */
const DERIVED = new Set(['formula', 'rules', 'keywords', 'model'])
const SOURCE_TONE: Record<string, 'accent' | 'ok' | 'neutral'> = { gemma: 'accent', 'gemma-vision': 'accent', human: 'ok' }

function fmt(key: string, v: unknown, templates?: Template[]): ReactNode {
  if (v == null || v === '') return <span className="text-subtle">—</span>
  if (/^route$/i.test(key) && typeof v === 'string') return <Pill tone={routeTone(v)}>{routeLabel(v, templates)}</Pill>
  if (typeof v === 'number') return isMoneyField(key) ? inr(v) : num(v, 2)
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  if (typeof v === 'object') return <Mono className="break-all">{JSON.stringify(v)}</Mono>
  const text = String(v)
  return text.length > 160 ? <span className="line-clamp-4" title={text}>{text}</span> : text
}

function FieldsPanel({ t }: { t: Task }) {
  const templates = useTemplates()
  const entries = Object.entries(t.fields ?? {}).filter(([k]) => !(t.kind === 'collection' && k.startsWith('draft_')))
  const doc = entries.filter(([, f]) => !DERIVED.has(f.source))
  const derived = entries.filter(([, f]) => DERIVED.has(f.source))
  if (!entries.length) return <Empty icon={FileText} title="Nothing extracted yet" body={t.status === 'queued' ? 'Run the case to read its documents.' : 'Fields appear as the employee reads the documents.'} className="h-full" />
  return (
    <div className="overflow-y-auto">
      <Section title="Extracted fields" hint={`${doc.length} from documents`}>
        {doc.map(([k, f]) => k === 'line_items' && Array.isArray(f.value) ? <LineItems key={k} f={f} /> : <FieldRow key={k} t={t} k={k} f={f} templates={templates.data} />)}
      </Section>
      {derived.length > 0 && <Section title="Derived by rules" hint="computed, not read">{derived.map(([k, f]) => <FieldRow key={k} t={t} k={k} f={f} templates={templates.data} />)}</Section>}
    </div>
  )
}

const Section = ({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) => (
  <section>
    <div className="sticky top-0 z-10 flex h-10 items-center gap-2 border-b border-line bg-panel/95 px-4 backdrop-blur">
      <h3 className="text-sm font-semibold">{title}</h3><span className="text-xs text-subtle">{hint}</span>
    </div>
    <dl className="divide-y divide-line">{children}</dl>
  </section>
)

function FieldRow({ t, k, f, templates }: { t: Task; k: string; f: Field; templates?: Template[] }) {
  const [editing, setEditing] = useState(false)
  const canCorrect = k === 'category' // corrections teach the employee's category model
  const tone = confidenceTone(f.confidence)
  return (
    <div className="px-4 py-2">
      <dt className="flex items-center gap-2 text-xs text-muted">
        <span className="min-w-0 flex-1 truncate" title={k}>{fieldLabel(k)}</span>
        <span className="flex items-center gap-1.5" title={`${Math.round(f.confidence * 100)}% confidence · source: ${f.source}`}>
          <Meter value={f.confidence} tone={tone} className="h-1 w-10" />
          <span className="w-7 text-right text-2xs text-subtle tnum">{Math.round(f.confidence * 100)}%</span>
          <Pill tone={SOURCE_TONE[f.source] ?? 'neutral'} className="h-4 px-1.5">{f.source}</Pill>
        </span>
      </dt>
      <dd className="mt-0.5 flex min-w-0 items-center gap-2 text-sm break-words">
        <div className="min-w-0 flex-1">{editing ? <CategoryEditor t={t} current={String(f.value ?? '')} done={() => setEditing(false)} /> : fmt(k, f.value, templates)}</div>
        {canCorrect && !editing && <Act perm="task.correct" size="sm" variant="ghost" icon={Pencil} onClick={() => setEditing(true)}>Correct</Act>}
      </dd>
    </div>
  )
}

function CategoryEditor({ t, current, done }: { t: Task; current: string; done: () => void }) {
  const l = useLearning(t.employee_id)
  const [v, setV] = useState(current)
  const save = useAction(() => api.post<{ n_corrections: number }>(`/tasks/${t.id}/correct`, { field: 'category', value: v }), {
    success: (r) => `Category corrected · ${r.n_corrections} correction(s) to learn from`, onDone: done,
  })
  return (
    <div className="flex items-center gap-1.5">
      <Select value={v} onChange={(e) => setV(e.target.value)} className="h-7 text-xs">
        {[...new Set([current, ...(l.data?.labels ?? [])])].filter(Boolean).map((x) => <option key={x}>{x}</option>)}
      </Select>
      <Button size="sm" variant="primary" loading={save.isPending} onClick={() => save.mutate()}>Save</Button>
      <Button size="sm" variant="ghost" onClick={done}>Cancel</Button>
    </div>
  )
}

function LineItems({ f }: { f: Field }) {
  const rows = f.value as { description?: string; qty?: number; rate?: number; amount?: number }[]
  return (
    <div className="px-4 py-2.5">
      <div className="mb-1.5 text-xs text-muted">Line items</div>
      <table className="w-full text-xs">
        <tbody className="divide-y divide-line">
          {rows.map((r, i) => (
            <tr key={i}><td className="py-1 pr-2">{r.description}</td><td className="py-1 text-right whitespace-nowrap text-muted tnum">{num(r.qty)} × {num(r.rate, 2)}</td><td className="py-1 pl-2 text-right whitespace-nowrap tnum">{inr(r.amount)}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ------------------------------------------------------------------ flags, steps, events */
const STEP_ICON: Record<StepRun['status'], [LucideIcon, string]> = {
  ok: [CheckCircle2, 'text-ok'], skipped: [CircleDashed, 'text-subtle'], failed: [XCircle, 'text-bad'], running: [Loader2, 'animate-spin text-accent'],
  retrying: [RotateCw, 'animate-spin text-warn'], waiting_approval: [Hand, 'text-accent'], simulated: [FlaskConical, 'text-muted'],
  fallback: [CornerDownRight, 'text-warn'], pending: [Circle, 'text-line-strong'],
}
const SEV: Record<Flag['severity'], [LucideIcon, string]> = { critical: [AlertOctagon, 'text-bad'], warn: [AlertTriangle, 'text-warn'], info: [Info, 'text-muted'] }

function RunPanel({ t }: { t: Task }) {
  const [tab, setTab] = useState<'steps' | 'events'>('steps')
  const events = useTaskEvents(t.id)
  return (
    <div className="overflow-y-auto">
      {t.flags.length > 0 && (
        <div className="space-y-2 border-b border-line p-4">
          <h3 className="text-sm font-semibold">Flags <span className="font-normal text-subtle">· {t.flags.length}</span></h3>
          {t.flags.map((f, i) => {
            const [Icon, cls] = SEV[f.severity] ?? SEV.info
            return (
              <div key={i} className={cn('rounded-md border p-2.5', f.severity === 'critical' ? 'border-bad/30 bg-bad/5' : f.severity === 'warn' ? 'border-warn/30 bg-warn/5' : 'border-line')}>
                <div className="flex items-center gap-1.5 text-sm font-medium"><Icon className={cn('size-3.5', cls)} />{humanize(f.type)}{f.step_id && <Mono className="ml-auto text-2xs">{f.step_id}</Mono>}</div>
                <p className="mt-1 text-xs text-muted">{f.message}</p>
                {f.evidence && <blockquote className="mt-2 rounded border-l-2 border-line-strong bg-sunken px-2 py-1.5 font-mono text-2xs leading-4 break-words text-muted">{f.evidence}</blockquote>}
              </div>
            )
          })}
        </div>
      )}
      <div className="sticky top-0 z-10 border-b border-line bg-panel/95 px-4 backdrop-blur">
        <Tabs value={tab} onChange={setTab} tabs={[{ id: 'steps', label: 'Step timeline', count: t.steps.length }, { id: 'events', label: 'Event log', count: events.data?.length }]} />
      </div>
      {tab === 'steps' ? (
        t.steps.length === 0 ? <Empty icon={Play} title="Not started" body="The step timeline fills in live as the case runs." /> : (
          <ol className="relative px-4 py-3">
            <span className="absolute top-5 bottom-5 left-[25px] w-px bg-line" />
            {t.steps.map((s) => <StepItem key={s.step_id} s={s} />)}
          </ol>
        )
      ) : (
        <Load q={events}>{(ev) => ev.length === 0 ? <Empty icon={Info} title="No events yet" /> : (
          <ol className="divide-y divide-line">
            {ev.map((e, i) => (
              <li key={i} className="flex gap-2.5 px-4 py-2 text-xs">
                <time className="shrink-0 font-mono text-subtle">{clock(e.ts)}</time>
                <span className={cn('mt-1.5 size-1.5 shrink-0 rounded-full', { info: 'bg-subtle', warn: 'bg-warn', error: 'bg-bad', success: 'bg-ok' }[e.level])} />
                <span className="min-w-0 flex-1 text-muted">{e.message}</span>
                {e.step_id && <Mono className="text-2xs text-subtle">{e.step_id}</Mono>}
              </li>
            ))}
          </ol>
        )}</Load>
      )}
    </div>
  )
}

function StepItem({ s }: { s: StepRun }) {
  const [open, setOpen] = useState(false)
  const [Icon, cls] = STEP_ICON[s.status] ?? STEP_ICON.pending
  return (
    <li className="relative flex gap-3 py-1.5">
      <span className="z-10 flex size-5 shrink-0 items-center justify-center rounded-full bg-panel"><Icon className={cn('size-4', cls)} /></span>
      <div className={cn('min-w-0 flex-1', s.status === 'skipped' && 'opacity-55')}>
        <button onClick={() => s.output_preview && setOpen((o) => !o)} className="flex w-full items-baseline gap-2 text-left">
          <span className="truncate text-sm">{s.title}</span>
          <Mono className="ml-auto shrink-0 text-2xs text-subtle">{s.step_id}</Mono>
        </button>
        <div className="flex flex-wrap items-center gap-x-2 text-2xs text-subtle">
          <span className="font-mono">{s.action}</span>
          {s.status !== 'ok' && s.status !== 'skipped' && <span className={cls.replace('animate-spin', '')}>{humanize(s.status)}</span>}
          {s.attempts > 1 && <span className="text-warn">{s.attempts} attempts</span>}
          {s.ai_calls > 0 && <span className="text-accent">{s.ai_calls} AI call{s.ai_calls > 1 ? 's' : ''}</span>}
        </div>
        {s.error && <p className="mt-1 rounded bg-bad/10 px-1.5 py-1 font-mono text-2xs break-words text-bad">{s.error}</p>}
        {open && s.output_preview && <pre className="mt-1.5 max-h-48 overflow-auto rounded border border-line bg-sunken p-2 font-mono text-2xs leading-4 whitespace-pre-wrap text-muted">{s.output_preview}</pre>}
      </div>
    </li>
  )
}
