import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { Brain, Download, FlaskConical, GitBranch, GitCompare, Inbox, IndianRupee, Play, RotateCcw, Save, ShieldCheck, Undo2, UserPlus, Users, Workflow } from 'lucide-react'
import { api, useAction, useEmployee, useEmployees, type CheckReport, type Employee, type Plan, type Step } from '../lib/api'
import { AUTONOMY, cn, inrShort, MONEY_ACTIONS, num, pct, sortEmployees } from '../lib/format'
import { CheckReportView, PlanGraph, stepsWithErrors } from '../components/plan-graph'
import { Act, AutonomyBadge, Avatar, Button, Empty, Input, Label, Load, Mono, PageHeader, Pill, SectorDot, Skeleton, Switch, Tabs, Textarea } from '../components/ui'
import { AutonomyTab, BacktestTab, LearningTab, VersionsTab } from './employee-tabs'

/* ================================================================== /employees */
export function WorkforcePage() {
  const emps = useEmployees()
  const nav = useNavigate()
  return (
    <div>
      <PageHeader title="Workforce" subtitle="Every digital employee, its SOP, autonomy and track record."
        actions={<Act perm="hire" variant="primary" icon={UserPlus} onClick={() => nav('/hire')}>Hire employee</Act>} />
      <div className="p-6">
        <Load q={emps} skeleton={<Skeleton className="h-64" />}>
          {(list) => list.length === 0 ? <Empty icon={Users} title="No employees yet" body="Hire one from an SOP to get started." /> : (
            <div className="overflow-hidden rounded-lg border border-line bg-panel">
              <table className="w-full text-sm">
                <thead className="border-b border-line bg-sunken text-left text-xs text-subtle">
                  <tr>{['Employee', 'Sector · department', 'Autonomy', 'Workflow', 'Accuracy', 'Handled', 'Open', 'Hours saved', 'Saved'].map((h, i) =>
                    <th key={h} className={cn('px-4 py-2 font-medium whitespace-nowrap', i > 3 && 'text-right')}>{h}</th>)}</tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {sortEmployees(list).map((e) => (
                    <tr key={e.id} onClick={() => nav(`/employees/${e.id}`)} className="cursor-pointer hover:bg-raised/50">
                      <td className="px-4 py-2.5"><div className="flex items-center gap-2.5"><Avatar emp={e} />
                        <div className="min-w-0"><div className="font-medium">{e.name}</div><div className="truncate text-xs text-muted">{e.role_title ?? e.role}</div></div></div></td>
                      <td className="px-4 py-2.5"><div className="flex items-center gap-1.5"><SectorDot sector={e.sector} />{e.sector}</div>
                        <div className="max-w-72 truncate pl-3.5 text-xs text-subtle">{[e.department, e.org].filter(Boolean).join(' · ')}</div></td>
                      <td className="px-4 py-2.5"><AutonomyBadge level={e.autonomy_level} label={e.autonomy_label} /></td>
                      <td className="px-4 py-2.5 whitespace-nowrap"><Mono>v{e.plan_version} · {e.plan.steps.length} steps</Mono></td>
                      <td className="px-4 py-2.5 text-right tnum">{pct(e.promotion.accuracy ?? e.kpis.accuracy)}</td>
                      <td className="px-4 py-2.5 text-right tnum">{num(e.kpis.tasks_done)}</td>
                      <td className="px-4 py-2.5 text-right tnum">{num(e.kpis.tasks_waiting_approval + e.kpis.tasks_in_review)}</td>
                      <td className="px-4 py-2.5 text-right tnum">{num(e.kpis.hours_saved, 1)}</td>
                      <td className="px-4 py-2.5 text-right tnum">{inrShort(e.kpis.money_saved_inr)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Load>
      </div>
    </div>
  )
}

/* ================================================================== /employees/:id */
type TabId = 'workflow' | 'backtest' | 'autonomy' | 'learning' | 'versions'

export function EmployeePage() {
  const { id } = useParams()
  const emp = useEmployee(id)
  const [sp, setSp] = useSearchParams()
  const tab = (sp.get('tab') as TabId) || 'workflow'
  return (
    <Load q={emp} skeleton={<div className="space-y-3 p-6"><Skeleton className="h-12 w-80" /><Skeleton className="h-[60vh]" /></div>}>
      {(e) => (
        <div className="flex h-full flex-col">
          <EmployeeHeader emp={e}>
            <Tabs value={tab} onChange={(t) => setSp({ tab: t }, { replace: true })} tabs={[
              { id: 'workflow', label: 'Workflow', icon: Workflow }, { id: 'backtest', label: 'Backtest', icon: FlaskConical },
              { id: 'autonomy', label: 'Autonomy', icon: ShieldCheck }, { id: 'learning', label: 'Learning', icon: Brain }, { id: 'versions', label: 'Versions', icon: GitCompare, count: e.plan_version },
            ]} />
          </EmployeeHeader>
          <div className="min-h-0 flex-1">
            {tab === 'workflow' ? <WorkflowTab key={`${e.id}:${e.plan_version}`} emp={e} />
              : <div className="h-full overflow-auto p-6">
                {tab === 'backtest' && <BacktestTab emp={e} />}
                {tab === 'autonomy' && <AutonomyTab emp={e} />}
                {tab === 'learning' && <LearningTab emp={e} />}
                {tab === 'versions' && <VersionsTab emp={e} />}
              </div>}
          </div>
        </div>
      )}
    </Load>
  )
}

function EmployeeHeader({ emp, children }: { emp: Employee; children: ReactNode }) {
  const ingest = useAction(() => api.post<{ created: unknown[] }>(`/employees/${emp.id}/ingest`), { success: (r) => `${r.created.length} new case(s) for ${emp.name}` })
  const run = useAction(() => api.post<{ started: number }>(`/employees/${emp.id}/run`, {}), { success: (r) => `${emp.name} started ${r.started} case(s)` })
  const k = emp.kpis
  return (
    <div className="border-b border-line bg-panel/40 px-6 pt-4">
      <div className="mb-3 text-xs text-subtle"><Link to="/employees" className="hover:text-fg">Workforce</Link> / {emp.name}</div>
      <div className="flex items-start gap-4">
        <Avatar emp={emp} size="lg" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2.5">
            <h1 className="text-xl font-semibold tracking-tight">{emp.name}</h1>
            <AutonomyBadge level={emp.autonomy_level} label={emp.autonomy_label} />
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-sm text-muted">
            <span className="text-fg">{emp.role_title ?? emp.role}</span><span className="text-subtle">·</span>
            <span className="flex items-center gap-1.5"><SectorDot sector={emp.sector} />{emp.sector}</span><span className="text-subtle">·</span>
            <span>{emp.department}</span>{emp.org && <><span className="text-subtle">·</span><span className="text-subtle">{emp.org}</span></>}
          </div>
          <Ladder level={emp.autonomy_level} />
        </div>
        <div className="flex items-center gap-2">
          <Act perm="work.run" icon={Download} loading={ingest.isPending} onClick={() => ingest.mutate()}>Ingest work</Act>
          <Act perm="work.run" variant="primary" icon={Play} loading={run.isPending} onClick={() => run.mutate()}>Run queue</Act>
        </div>
      </div>
      <dl className="mt-4 flex flex-wrap gap-x-8 gap-y-2 pb-4">
        {[['Backtest accuracy', pct(emp.promotion.accuracy)], ['Cases handled', num(k.tasks_done)], ['Awaiting / review', `${k.tasks_waiting_approval} / ${k.tasks_in_review}`],
          ['Hours saved', num(k.hours_saved, 1)], ['Cost saved', inrShort(k.money_saved_inr)], ['AI calls / case', num(k.ai_calls_per_task, 1)], ['Escalation rate', pct(k.escalation_rate)]].map(([l, v]) => (
          <div key={l}><dt className="text-xs text-subtle">{l}</dt><dd className="text-base font-semibold tnum">{v}</dd></div>
        ))}
        <div className="min-w-0"><dt className="text-xs text-subtle">Intake channel</dt>
          <dd className="mt-0.5 flex items-center gap-1.5 truncate text-sm">{emp.intake ? <><Pill icon={Inbox}>{emp.intake.type}</Pill><Mono className="truncate">{emp.intake.path}</Mono></> : <span className="text-subtle">—</span>}</dd></div>
      </dl>
      {children}
    </div>
  )
}

function Ladder({ level }: { level: number }) {
  return (
    <ol className="mt-2.5 flex items-center gap-1.5 text-xs">
      {AUTONOMY.map((a, i) => (
        <li key={a.label} className="flex items-center gap-1.5">
          {i > 0 && <span className={cn('h-px w-6', i <= level ? 'bg-accent' : 'bg-line-strong')} />}
          <span className={cn('flex items-center gap-1 rounded-full px-2 py-0.5', i === level ? 'bg-accent/15 font-medium text-accent' : i < level ? 'text-muted' : 'text-subtle')}>
            <span className={cn('size-1.5 rounded-full', i <= level ? 'bg-accent' : 'border border-line-strong')} />{a.label}
          </span>
        </li>
      ))}
    </ol>
  )
}

/* ------------------------------------------------------------------ Workflow tab: graph + step editor */
function WorkflowTab({ emp }: { emp: Employee }) {
  const [draft, setDraft] = useState<Plan>(() => structuredClone(emp.plan))
  const [sel, setSel] = useState<string | null>(null)
  const [report, setReport] = useState<CheckReport | null>(null)
  const original = useMemo(() => new Map(emp.plan.steps.map((s) => [s.id, JSON.stringify(s)])), [emp.plan])
  const edited = useMemo(() => new Set(draft.steps.filter((s) => original.get(s.id) !== JSON.stringify(s)).map((s) => s.id)), [draft, original])
  const errors = useMemo(() => stepsWithErrors(report), [report])
  const step = draft.steps.find((s) => s.id === sel)
  const reportRef = useRef<HTMLDivElement>(null)
  useEffect(() => { if (report) reportRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }) }, [report])
  const update = (patch: Partial<Step>) => setDraft((d) => ({ ...d, steps: d.steps.map((s) => (s.id === sel ? { ...s, ...patch } : s)) }))

  const check = useAction(() => api.post<CheckReport>(`/employees/${emp.id}/plan/check`, { plan: draft }), {
    onDone: (r) => { setReport(r); if (r.ok) toast.success('All 8 checks passed'); else toast.error(`${r.errors.length} problem(s) found`) },
  })
  const save = useAction(() => api.put<{ employee: Employee; check: CheckReport }>(`/employees/${emp.id}/plan`, { plan: draft, note: `Edited ${[...edited].join(', ')} in console` }), {
    onDone: (r) => {
      setReport(r.check)
      if (r.check.ok) toast.success(`Saved as v${r.employee.plan_version}`)
      else toast.error('Not saved — the checker found problems', { description: r.check.errors[0] })
    },
  })

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col bg-canvas">
        <div className="flex h-10 shrink-0 items-center gap-2 border-b border-line px-4 text-xs text-subtle">
          <span className="mr-1 whitespace-nowrap">{draft.steps.length} steps</span>
          <Pill icon={GitBranch}>Dashed = conditional</Pill><Pill tone="accent" icon={ShieldCheck}>Approval gate</Pill><Pill tone="warn" icon={IndianRupee}>Moves money</Pill>
          <span className="ml-auto whitespace-nowrap">Scroll to pan · click a step to edit</span>
        </div>
        <div className="min-h-0 flex-1"><PlanGraph plan={draft} selected={sel} onSelect={setSel} edited={edited} errors={errors} /></div>
      </div>
      <aside className="flex w-[400px] shrink-0 flex-col border-l border-line bg-panel">
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-4">
          {step ? <StepEditor key={step.id} step={step} onChange={update} onRevert={() => setDraft((d) => ({ ...d, steps: d.steps.map((s) => (s.id === sel ? JSON.parse(original.get(s.id)!) : s)) }))} />
            : <PlanSummary emp={emp} plan={draft} />}
          {report && <div ref={reportRef}><CheckReportView report={report} compact /></div>}
        </div>
        <footer className="flex items-center gap-2 border-t border-line p-3">
          <span className="mr-auto text-xs text-subtle">{edited.size ? `${edited.size} step(s) edited` : 'No changes'}</span>
          {edited.size > 0 && <Button size="sm" variant="ghost" icon={Undo2} onClick={() => { setDraft(structuredClone(emp.plan)); setReport(null) }}>Discard</Button>}
          <Act perm="plan.check" size="sm" icon={ShieldCheck} loading={check.isPending} onClick={() => check.mutate()}>Check</Act>
          <Act perm="plan.edit" size="sm" variant="primary" icon={Save} disabled={!edited.size} loading={save.isPending} onClick={() => save.mutate()}>Save as v{emp.plan_version + 1}</Act>
        </footer>
      </aside>
    </div>
  )
}

function PlanSummary({ emp, plan }: { emp: Employee; plan: Plan }) {
  const s = plan.steps
  const stats = [['Steps', s.length], ['Conditional', s.filter((x) => x.when).length], ['Approval gates', s.filter((x) => x.requires_approval).length],
    ['Side effects', s.filter((x) => x.side_effect).length], ['Move money', s.filter((x) => MONEY_ACTIONS.has(x.action)).length]] as const
  return (
    <div className="space-y-4">
      <div>
        <div className="text-2xs font-medium tracking-wider text-subtle uppercase">Plan v{emp.plan_version}</div>
        <h3 className="mt-1 text-sm font-semibold">{plan.name}</h3>
        <p className="mt-1 text-xs leading-relaxed text-muted">{plan.description}</p>
        <p className="mt-2 text-xs text-subtle">Compiled from <span className="text-muted">{emp.sop_title}</span></p>
      </div>
      <dl className="grid grid-cols-5 divide-x divide-line rounded-md border border-line">
        {stats.map(([l, v]) => <div key={l} className="px-2 py-2 text-center"><dd className="text-base font-semibold tnum">{v}</dd><dt className="text-2xs leading-tight text-subtle">{l}</dt></div>)}
      </dl>
      <p className="rounded-md border border-dashed border-line-strong p-3 text-xs text-muted">Select a step in the graph to edit its parameters, guard, retries or approval — then <b className="text-fg">Check</b> it against the 8 compiler checks and save a new version.</p>
      <div>
        <Label hint={`${emp.tools.length} granted`}>Tools (least privilege)</Label>
        <div className="flex flex-wrap gap-1">{emp.tools.map((t) => <span key={t} className="rounded border border-line bg-sunken px-1.5 py-0.5 font-mono text-2xs text-muted">{t}</span>)}</div>
      </div>
    </div>
  )
}

function StepEditor({ step, onChange, onRevert }: { step: Step; onChange: (p: Partial<Step>) => void; onRevert: () => void }) {
  const [text, setText] = useState(() => JSON.stringify(step.params, null, 2))
  const [err, setErr] = useState<string | null>(null)
  const onParams = (v: string) => {
    setText(v)
    try { onChange({ params: JSON.parse(v) }); setErr(null) } catch (e) { setErr((e as Error).message) }
  }
  return (
    <div className="space-y-4">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 font-mono text-2xs text-subtle"><span className="rounded bg-raised px-1 text-muted">{step.id}</span>{step.action}</div>
          <h3 className="mt-1 text-sm font-semibold">{step.title}</h3>
        </div>
        <Button size="sm" variant="ghost" icon={RotateCcw} onClick={onRevert}>Revert</Button>
      </div>
      <div><Label>Title</Label><Input value={step.title} onChange={(e) => onChange({ title: e.target.value })} /></div>
      <div><Label hint="empty = always runs">Guard (when)</Label>
        <Input className="font-mono text-xs" placeholder="e.g. s10.route == 'approval'" value={step.when ?? ''} onChange={(e) => onChange({ when: e.target.value.trim() ? e.target.value : null })} /></div>
      <div className="grid grid-cols-2 gap-3">
        <div><Label>Retries</Label><Input type="number" min={0} max={5} value={step.on_error.retry} onChange={(e) => onChange({ on_error: { ...step.on_error, retry: Math.max(0, Math.min(5, Number(e.target.value) || 0)) } })} /></div>
        <div><Label>Fallback</Label><Input className="font-mono text-xs" placeholder="none" value={step.on_error.fallback ?? ''} onChange={(e) => onChange({ on_error: { ...step.on_error, fallback: e.target.value || null } })} /></div>
      </div>
      <div className="flex items-center justify-between rounded-md border border-line px-3 py-2.5">
        <div><div className="text-sm font-medium">Requires approval</div><div className="text-xs text-subtle">Pause for a human before this step runs</div></div>
        <Switch checked={step.requires_approval} onChange={(v) => onChange({ requires_approval: v })} label="Requires approval" />
      </div>
      <div className="flex items-center gap-2 text-xs text-subtle">
        {step.side_effect ? <Pill tone="warn">Side effect</Pill> : <Pill>Read-only</Pill>}
        {MONEY_ACTIONS.has(step.action) && <Pill tone="warn" icon={IndianRupee}>Moves money</Pill>}
        <span>set by the tool registry</span>
      </div>
      <div>
        <Label hint={err ? <span className="text-bad">invalid JSON</span> : 'JSON'}>Parameters</Label>
        <Textarea spellCheck={false} rows={14} value={text} onChange={(e) => onParams(e.target.value)}
          className={cn('font-mono text-xs leading-5', err && 'border-bad focus:border-bad')} />
        {err && <p className="mt-1 font-mono text-2xs text-bad">{err}</p>}
      </div>
    </div>
  )
}
