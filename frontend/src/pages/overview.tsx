import { Link, useNavigate } from 'react-router-dom'
import { Activity, AlertTriangle, ArrowUpRight, CheckCircle2, Circle, Clock, Cpu, FileStack, Inbox, IndianRupee, ListChecks, Sparkles, UserPlus, XCircle } from 'lucide-react'
import { api, useAction, useEmployees, useInbox, useOverview, useSettings, useTasks, useTemplates, useWorkspace, type Employee, type Overview, type Task, type Template } from '../lib/api'
import { ago, clock, inrShort, num, pct, sectorMeta, sortEmployees } from '../lib/format'
import { AiCallsTrend, IssuesByType, OutcomesBySector, Sparkline, type OutcomeRow } from '../components/charts'
import { Act, AutonomyBadge, Avatar, Button, Empty, Load, PageHeader, Panel, PanelHead, SectorDot, Skeleton, Stat } from '../components/ui'
import { SetupPage } from './setup'

export function OverviewPage() {
  const ws = useWorkspace()
  const emps = useEmployees()
  if (ws.data && !ws.data.org?.name) return <SetupPage /> // first run: no organisation profile yet
  if (emps.data?.length === 0) return <EmptyWorkforce />
  return <Cockpit />
}

function EmptyWorkforce() {
  const ws = useWorkspace()
  const templates = useTemplates()
  const nav = useNavigate()
  const demo = useAction(() => api.post('/workspace/demo'), { success: 'Demo workspace ready — meet your team' })
  return (
    <div>
      <PageHeader title="Owner cockpit" subtitle={`${ws.data?.org?.name ?? 'Your workspace'} · no digital employees yet`} />
      <div className="space-y-6 p-6">
        <Panel className="relative overflow-hidden">
          <div className="absolute inset-0 bg-[radial-gradient(600px_200px_at_15%_0%,color-mix(in_oklab,var(--accent)_14%,transparent),transparent)]" />
          <div className="relative flex flex-col items-start gap-4 p-8 md:flex-row md:items-center">
            <span className="flex size-12 items-center justify-center rounded-xl border border-accent/30 bg-accent/10 text-accent"><UserPlus className="size-5" /></span>
            <div className="flex-1">
              <h2 className="text-lg font-semibold tracking-tight">Hire your first digital employee</h2>
              <p className="mt-1 max-w-2xl text-sm text-muted">Pick a template or upload your own SOP. Prompt2Process asks about the gaps, compiles a checked workflow and starts the employee in Shadow mode — your dashboards fill in as it works.</p>
            </div>
            <div className="flex gap-2">
              {ws.data?.demo_available && <Act perm="admin" icon={Sparkles} loading={demo.isPending} onClick={() => demo.mutate()}>{demo.isPending ? 'Hiring demo team…' : 'Load demo workspace'}</Act>}
              <Act perm="hire" variant="primary" icon={UserPlus} onClick={() => nav('/hire')}>Hire from an SOP</Act>
            </div>
          </div>
        </Panel>
        <section>
          <div className="mb-2.5 flex items-baseline gap-2"><h2 className="text-sm font-semibold">Start from a template</h2><span className="text-xs text-subtle">Every template is a real SOP you can edit before hiring</span></div>
          <Load q={templates}>{(list) => list.length ? (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">{list.map((t) => <HireCard key={t.id} t={t} />)}</div>
          ) : <Empty icon={FileStack} title="No templates available" body="Upload your own SOP from the Hire page." />}</Load>
        </section>
      </div>
    </div>
  )
}

function Cockpit() {
  const ov = useOverview()
  const emps = useEmployees()
  const tasks = useTasks()
  const templates = useTemplates()
  const inbox = useInbox()
  const nav = useNavigate()
  const team = sortEmployees(emps.data ?? [])
  const openInbox = inbox.data?.length ?? ov.data?.open_inbox ?? 0

  return (
    <div>
      <PageHeader
        title="Owner cockpit"
        subtitle={`${team.length} digital employees across ${new Set(team.map((e) => e.sector)).size} sectors · live`}
        actions={<>
          <Button icon={Inbox} onClick={() => nav('/inbox')}>Inbox{openInbox ? ` · ${openInbox}` : ''}</Button>
          <Act perm="hire" variant="primary" icon={UserPlus} onClick={() => nav('/hire')}>Hire employee</Act>
        </>}
      />
      <div className="space-y-5 p-6">
        <Load q={ov} skeleton={<Skeleton className="h-[92px]" />}>{(o) => <Kpis o={o} openInbox={openInbox} />}</Load>

        <section>
          <div className="mb-2.5 flex items-baseline gap-2">
            <h2 className="text-sm font-semibold">Sectors</h2>
            <span className="text-xs text-subtle">Your digital employees, grouped by sector · click to open</span>
          </div>
          <Load q={emps} skeleton={<div className="grid grid-cols-3 gap-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-[172px]" />)}</div>}>
            {() => (
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                {team.map((e) => <EmployeeCard key={e.id} emp={e} tasks={tasks.data ?? []} />)}
                {(templates.data ?? []).filter((t) => !t.hired_count).map((t) => <HireCard key={t.id} t={t} />)}
              </div>
            )}
          </Load>
        </section>

        <div className="grid grid-cols-1 gap-5 xl:grid-cols-12">
          <Panel className="xl:col-span-7">
            <PanelHead title="Outcomes by sector" hint="Per digital employee · live work only" />
            <div className="p-4">
              <Load q={tasks}>{(t) => (t.some((x) => x.mode !== 'shadow')
                ? <OutcomesBySector data={outcomeRows(t, team)} />
                : <Empty icon={ListChecks} title="No live work yet" body="Ingest and run a queue to see outcomes here." />)}
              </Load>
            </div>
          </Panel>
          <Panel className="xl:col-span-5">
            <PanelHead title="Issues caught" hint="Flags raised by checks, by type" />
            <div className="p-4">
              <Load q={ov}>{(o) => (Object.keys(o.flags_by_type).length
                ? <IssuesByType data={o.flags_by_type} />
                : <Empty icon={CheckCircle2} title="Nothing flagged yet" body="Duplicates, mismatches and injections will appear here." />)}
              </Load>
            </div>
          </Panel>
          <Panel className="xl:col-span-7">
            <PanelHead title="AI calls per task" hint="Falls as employees learn from corrections and templates take over"
              actions={ov.data && <AiTrendStat s={ov.data.ai_calls_series} />} />
            <div className="p-4 pt-3">
              <Load q={ov}>{(o) => (o.ai_calls_series.length > 1
                ? <AiCallsTrend series={o.ai_calls_series} />
                : <Empty icon={Cpu} title="Not enough finished tasks" body="The trend appears after a couple of tasks complete." />)}
              </Load>
            </div>
          </Panel>
          <Panel className="flex flex-col xl:col-span-5">
            <PanelHead title="Live activity" hint="Latest events across every employee" actions={<span className="flex items-center gap-1.5 text-xs text-ok"><span className="size-1.5 animate-ping-soft rounded-full bg-ok" />Live</span>} />
            <Load q={ov}>{(o) => <ActivityFeed o={o} tasks={tasks.data ?? []} team={team} />}</Load>
          </Panel>
        </div>
      </div>
    </div>
  )
}

function AiTrendStat({ s }: { s: Overview['ai_calls_series'] }) {
  const avg = (xs: typeof s) => (xs.length ? xs.reduce((a, p) => a + p.ai_calls, 0) / xs.length : 0)
  if (s.length < 2) return null
  return <span className="text-xs text-muted">first 10 <b className="text-fg tnum">{num(avg(s.slice(0, 10)), 1)}</b> → last 10 <b className="text-fg tnum">{num(avg(s.slice(-10)), 1)}</b></span>
}

function Kpis({ o, openInbox }: { o: Overview; openInbox: number }) {
  const s = useSettings()
  return (
    <Panel className="grid grid-cols-2 divide-line md:grid-cols-5 md:divide-x">
      <Stat icon={Clock} label="Hours saved" value={num(o.hours_saved, 1)} hint={`vs. manual processing`} />
      <Stat icon={IndianRupee} label="Cost saved" value={inrShort(o.money_saved_inr)} hint={s.data ? `at ₹${num(s.data.hourly_cost_inr)}/hour` : ' '} />
      <Stat icon={ListChecks} label="Cases handled" value={num(o.tasks_done)} hint={`${o.employees} employees`} />
      <Stat icon={Inbox} label="Open inbox" value={num(openInbox)} hint="approvals · reviews · fixes" />
      <Stat icon={Cpu} label="AI calls / case" value={num(o.ai_calls_total / Math.max(1, o.tasks_done), 1)} hint={`${num(o.ai_calls_total)} calls total`} />
    </Panel>
  )
}

function EmployeeCard({ emp, tasks }: { emp: Employee; tasks: Task[] }) {
  const k = emp.kpis
  const color = sectorMeta(emp.sector).color
  const mine = tasks.filter((t) => t.employee_id === emp.id)
  const timed = mine.filter((t) => t.duration_s != null).sort((a, b) => a.updated_at.localeCompare(b.updated_at)).slice(-20).map((t) => t.duration_s!)
  const avg = timed.length ? timed.reduce((a, b) => a + b, 0) / timed.length : null
  const queued = mine.filter((t) => t.status === 'queued' || t.status === 'running').length
  const acc = emp.promotion.accuracy ?? k.accuracy
  return (
    <Link to={`/employees/${emp.id}`} className="group relative block overflow-hidden rounded-lg border border-line bg-panel p-4 transition-colors hover:border-line-strong hover:bg-raised/40">
      <span className="absolute inset-x-0 top-0 h-[2px] opacity-80" style={{ background: color }} />
      <div className="flex items-start gap-3">
        <Avatar emp={emp} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="font-semibold">{emp.name}</span>
            <ArrowUpRight className="size-3.5 text-subtle opacity-0 transition-opacity group-hover:opacity-100" />
          </div>
          <div className="truncate text-xs text-muted">{emp.role_title ?? emp.role}</div>
        </div>
        <AutonomyBadge level={emp.autonomy_level} label={emp.autonomy_label} />
      </div>
      <div className="mt-2.5 flex items-center gap-1.5 truncate text-xs text-subtle">
        <SectorDot sector={emp.sector} /> <span className="text-muted">{emp.sector}</span> · <span className="truncate">{emp.department}</span>
      </div>
      <dl className="mt-3.5 grid grid-cols-4 gap-2 border-t border-line pt-3">
        {[['Accuracy', pct(acc)], ['Handled', num(k.tasks_done)], ['In queue', num(queued + k.tasks_waiting_approval)], ['Review', num(k.tasks_in_review)]].map(([l, v]) => (
          <div key={l}>
            <dt className="text-2xs text-subtle">{l}</dt>
            <dd className="text-sm font-medium tnum">{v}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-3 flex items-center gap-3">
        <div className="w-24 shrink-0 text-2xs leading-tight text-subtle">Time per case<span className="block text-xs font-medium text-muted tnum">{avg == null ? '—' : `${num(avg, 1)}s`} <span className="font-normal text-subtle">· {num(k.ai_calls_per_task, 1)} AI</span></span></div>
        <div className="min-w-0 flex-1">{timed.length > 1 ? <Sparkline values={timed} color={color} /> : <div className="h-7 border-b border-dashed border-line-strong" />}</div>
      </div>
    </Link>
  )
}

function HireCard({ t }: { t: Template }) {
  const docs = Object.keys(t.documents ?? {}).length
  const routes = Object.keys(t.routes ?? {}).length
  return (
    <Link to={`/hire?template=${t.id}`} className="group flex flex-col rounded-lg border border-dashed border-line-strong p-4 transition-colors hover:border-accent/50 hover:bg-raised/40">
      <div className="flex items-center gap-1.5 text-xs text-subtle"><SectorDot sector={t.sector} />{t.sector}</div>
      <div className="mt-2 font-medium">{t.employee.title}</div>
      <div className="truncate text-xs text-muted">{t.department} · {t.case_noun}s</div>
      <div className="mt-3 flex-1 text-xs text-subtle">{[docs && `${docs} document${docs === 1 ? '' : 's'} per case`, routes && `${routes} outcomes`, t.intake && `intake: ${t.intake.type}`, t.hired_count && `${t.hired_count} hired`].filter(Boolean).join(' · ')}</div>
      <span className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-accent">Hire {t.employee.name ? `as ${t.employee.name}` : 'from template'}<ArrowUpRight className="size-3.5 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" /></span>
    </Link>
  )
}

function outcomeRows(tasks: Task[], team: Employee[]): OutcomeRow[] {
  const rows = new Map<string, OutcomeRow>()
  for (const e of team) rows.set(e.id, { sector: `${sectorMeta(e.sector).short} · ${e.name}`, done: 0, waiting: 0, review: 0, stopped: 0, active: 0 })
  for (const t of tasks) {
    if (t.mode === 'shadow') continue
    const r = rows.get(t.employee_id)
    if (!r) continue
    const k = t.status === 'done' ? 'done' : t.status === 'waiting_approval' ? 'waiting' : t.status === 'needs_review' ? 'review'
      : t.status === 'rejected' || t.status === 'failed' ? 'stopped' : 'active'
    r[k] += 1
  }
  return [...rows.values()]
}

const LEVEL_ICON = { success: [CheckCircle2, 'text-ok'], warn: [AlertTriangle, 'text-warn'], error: [XCircle, 'text-bad'], info: [Circle, 'text-subtle'] } as const

function ActivityFeed({ o, tasks, team }: { o: Overview; tasks: Task[]; team: Employee[] }) {
  if (!o.activity.length) return <Empty icon={Activity} title="Quiet for now" body="Events stream in here as employees work." />
  const task = new Map(tasks.map((t) => [t.id, t]))
  const emp = new Map(team.map((e) => [e.id, e]))
  return (
    <ol className="max-h-[236px] flex-1 divide-y divide-line overflow-y-auto">
      {o.activity.map((ev, i) => {
        const t = ev.task_id ? task.get(ev.task_id) : undefined
        const e = t ? emp.get(t.employee_id) : undefined
        const [Icon, cls] = LEVEL_ICON[ev.level] ?? LEVEL_ICON.info
        return (
          <li key={`${ev.ts}-${i}`}>
            <Link to={ev.task_id ? `/work/${ev.task_id}` : '#'} className="flex items-start gap-2.5 px-4 py-2 hover:bg-raised/50">
              <Icon className={`mt-0.5 size-3.5 shrink-0 ${cls}`} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm">{ev.message}</p>
                <p className="flex items-center gap-1.5 truncate text-xs text-subtle">
                  {e && <><SectorDot sector={e.sector} />{e.name} ·</>} <span className="truncate">{t?.title ?? ev.task_id}</span>
                </p>
              </div>
              <time className="shrink-0 font-mono text-2xs text-subtle" title={ago(ev.ts)}>{clock(ev.ts)}</time>
            </Link>
          </li>
        )
      })}
    </ol>
  )
}
