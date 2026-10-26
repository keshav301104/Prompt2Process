import { useNavigate, useSearchParams } from 'react-router-dom'
import { Download, Inbox, Play, Search, UserPlus } from 'lucide-react'
import { api, useAction, useEmployees, useTasks, useTemplates, type Employee, type Task } from '../lib/api'
import { ago, cn, humanize, num, routeLabel, routeTone, sectorMeta, shortId, sortEmployees } from '../lib/format'
import { Act, Avatar, Empty, Input, Load, Mono, PageHeader, Panel, Pill, Segmented, Select, Skeleton, StatusPill } from '../components/ui'

const GROUPS = {
  all: () => true,
  active: (t: Task) => t.status === 'queued' || t.status === 'running',
  waiting: (t: Task) => t.status === 'waiting_approval',
  review: (t: Task) => t.status === 'needs_review',
  done: (t: Task) => t.status === 'done',
  stopped: (t: Task) => t.status === 'rejected' || t.status === 'failed',
}
type Group = keyof typeof GROUPS

export function WorkPage() {
  const tasks = useTasks()
  const emps = useEmployees()
  const templates = useTemplates()
  const nav = useNavigate()
  const [sp, setSp] = useSearchParams()
  const f = { employee: sp.get('employee') ?? '', sector: sp.get('sector') ?? '', status: (sp.get('status') as Group) || 'all', q: sp.get('q') ?? '' }
  const set = (k: string, v: string) => { const n = new URLSearchParams(sp); if (v && v !== 'all') n.set(k, v); else n.delete(k); setSp(n, { replace: true }) }
  const team = sortEmployees(emps.data ?? [])
  const empById = new Map(team.map((e) => [e.id, e]))
  const all = tasks.data ?? []
  const rows = all.filter((t) => {
    const e = empById.get(t.employee_id)
    return (!f.employee || t.employee_id === f.employee) && (!f.sector || e?.sector === f.sector) && GROUPS[f.status](t)
      && (!f.q || `${t.title} ${t.id} ${t.case_id ?? ''}`.toLowerCase().includes(f.q.toLowerCase()))
  })
  const inFlight = all.filter((t) => GROUPS.active(t)).length

  return (
    <div>
      <PageHeader title="Work queue" subtitle={`${num(all.length)} cases · ${inFlight} in flight · updates live`} />
      <div className="space-y-4 p-6">
        {emps.data?.length === 0 && (
          <Panel><Empty icon={UserPlus} title="No digital employees yet" body="Hire one from a template or your own SOP — its intake channel feeds this queue."
            action={<Act perm="hire" variant="primary" icon={UserPlus} onClick={() => nav('/hire')}>Hire an employee</Act>} /></Panel>
        )}
        <div className="grid grid-cols-[repeat(auto-fill,minmax(176px,1fr))] gap-3">
          {team.map((e) => <Lane key={e.id} emp={e} tasks={all.filter((t) => t.employee_id === e.id)} active={f.employee === e.id} onPick={() => set('employee', f.employee === e.id ? '' : e.id)} />)}
        </div>

        <div className="overflow-hidden rounded-lg border border-line bg-panel">
          <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2.5">
            <div className="relative w-64">
              <Search className="pointer-events-none absolute top-2 left-2.5 size-4 text-subtle" />
              <Input className="pl-8" placeholder="Search cases or ids" value={f.q} onChange={(e) => set('q', e.target.value)} />
            </div>
            <Select className="w-48" value={f.sector} onChange={(e) => set('sector', e.target.value)}>
              <option value="">All sectors</option>
              {[...new Set(team.map((e) => e.sector))].map((s) => <option key={s} value={s}>{s}</option>)}
            </Select>
            <Select className="w-44" value={f.employee} onChange={(e) => set('employee', e.target.value)}>
              <option value="">All employees</option>
              {team.map((e) => <option key={e.id} value={e.id}>{e.name} · {sectorMeta(e.sector).short}</option>)}
            </Select>
            <div className="ml-auto"><Segmented value={f.status} onChange={(v) => set('status', v)} options={[
              { id: 'all', label: 'All' }, { id: 'active', label: 'In flight' }, { id: 'waiting', label: 'Awaiting' },
              { id: 'review', label: 'Review' }, { id: 'done', label: 'Done' }, { id: 'stopped', label: 'Rejected' }]} /></div>
          </div>
          <Load q={tasks} skeleton={<div className="space-y-2 p-4">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-9" />)}</div>}>
            {() => rows.length === 0 ? (
              <Empty icon={Inbox} title={all.length ? 'No cases match these filters' : 'No cases yet'}
                body={all.length ? 'Clear a filter to see more.' : 'Use “Ingest” on an employee above to pull new work from their inbox, then “Run”.'} />
            ) : (
              <table className="w-full text-sm">
                <thead className="border-b border-line bg-sunken text-left text-xs text-subtle">
                  <tr>{['Case', 'Employee', 'Status', 'Flags', 'Outcome', 'AI', 'Took', 'Updated'].map((h, i) => <th key={h} className={cn('px-3 py-2 font-medium first:pl-4', i >= 5 && 'text-right last:pr-4')}>{h}</th>)}</tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {rows.map((t) => {
                    const e = empById.get(t.employee_id)
                    const route = t.outcome?.final_decision ?? t.outcome?.route
                    return (
                      <tr key={t.id} onClick={() => nav(`/work/${t.id}`)} className="cursor-pointer hover:bg-raised/50">
                        <td className="max-w-80 py-2 pr-3 pl-4">
                          <div className="truncate font-medium">{t.title}</div>
                          <Mono className="text-2xs text-subtle">{t.case_id ?? shortId(t.id)} · {t.kind}{t.mode === 'shadow' ? ' · shadow' : ''}</Mono>
                        </td>
                        <td className="px-3 py-2">{e && <span className="flex items-center gap-2"><Avatar emp={e} size="sm" /><span className="truncate">{e.name}</span></span>}</td>
                        <td className="px-3 py-2"><StatusPill status={t.status} /></td>
                        <td className="px-3 py-2"><div className="flex max-w-60 flex-wrap gap-1">
                          {t.flags.slice(0, 2).map((fl, i) => <Pill key={i} tone={fl.severity === 'critical' ? 'bad' : fl.severity === 'warn' ? 'warn' : 'neutral'}>{humanize(fl.type)}</Pill>)}
                          {t.flags.length > 2 && <Pill>+{t.flags.length - 2}</Pill>}
                          {!t.flags.length && <span className="text-subtle">—</span>}
                        </div></td>
                        <td className="px-3 py-2">{route ? <Pill tone={routeTone(route)}>{routeLabel(route, templates.data)}</Pill> : <span className="text-subtle">—</span>}</td>
                        <td className="px-3 py-2 text-right tnum text-muted">{t.ai_calls}</td>
                        <td className="px-3 py-2 text-right tnum text-muted">{t.duration_s == null ? '—' : `${num(t.duration_s, 1)}s`}</td>
                        <td className="py-2 pr-4 pl-3 text-right text-xs whitespace-nowrap text-subtle">{ago(t.updated_at)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </Load>
        </div>
      </div>
    </div>
  )
}

function Lane({ emp, tasks, active, onPick }: { emp: Employee; tasks: Task[]; active: boolean; onPick: () => void }) {
  const ingest = useAction(() => api.post<{ created: unknown[] }>(`/employees/${emp.id}/ingest`), {
    success: (r) => (r.created.length ? `${r.created.length} new case(s) for ${emp.name}` : `No new work in ${emp.name}’s inbox`),
  })
  const run = useAction(() => api.post<{ started: number }>(`/employees/${emp.id}/run`, {}), {
    success: (r) => (r.started ? `${emp.name} started ${r.started} case(s)` : 'Nothing queued to run'),
  })
  const queued = tasks.filter((t) => t.status === 'queued').length
  const running = tasks.filter((t) => t.status === 'running').length
  return (
    <div className={cn('rounded-lg border bg-panel p-3 transition-colors', active ? 'border-accent ring-2 ring-accent/20' : 'border-line')}>
      <button onClick={onPick} className="flex w-full items-center gap-2.5 text-left" title="Filter the table to this employee">
        <Avatar emp={emp} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{emp.name}</div>
          <div className="truncate text-xs text-subtle">{sectorMeta(emp.sector).short} · {emp.autonomy_label}</div>
        </div>
      </button>
      <div className="mt-2.5 flex gap-2.5 text-xs text-muted">
        <span><b className="font-medium text-fg tnum">{tasks.length}</b> cases</span>
        <span><b className="font-medium text-fg tnum">{queued}</b> queued</span>
        {running > 0 && <span className="text-accent"><b className="font-medium tnum">{running}</b> running</span>}
      </div>
      <div className="mt-2.5 grid grid-cols-2 gap-1.5">
        <Act perm="work.run" block size="sm" icon={Download} loading={ingest.isPending} onClick={() => ingest.mutate()}>Ingest</Act>
        <Act perm="work.run" block size="sm" variant={queued ? 'primary' : 'secondary'} icon={Play} loading={run.isPending} onClick={() => run.mutate()}>Run{queued ? ` ${queued}` : ''}</Act>
      </div>
    </div>
  )
}
