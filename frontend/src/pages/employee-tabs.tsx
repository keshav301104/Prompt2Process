import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Brain, Check, CheckCircle2, FlaskConical, GitCompare, History, Sparkles, TrendingDown, TrendingUp, XCircle } from 'lucide-react'
import { api, useAction, useBacktest, useBacktests, useDiff, useLearning, useVersions, type Backtest, type Employee } from '../lib/api'
import { ago, AUTONOMY, cn, humanize, inr, inrShort, num, pct, stamp } from '../lib/format'
import { Act, Empty, Load, Meter, Mono, Panel, PanelHead, Pill, Segmented, Stat, Tip } from '../components/ui'

const issueChips = (list: string[], tone: 'neutral' | 'warn') =>
  list.length ? <div className="flex flex-wrap gap-1">{list.map((i) => <Pill key={i} tone={tone}>{humanize(i)}</Pill>)}</div> : <span className="text-subtle">—</span>

/* ================================================================== Backtest */
export function BacktestTab({ emp }: { emp: Employee }) {
  const list = useBacktests(emp.id)
  const [started, setStarted] = useState<string | null>(null)
  const history = [...(list.data ?? [])].sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))
  const id = started ?? history[0]?.id ?? null
  const bt = useBacktest(id)
  const run = useAction(() => api.post<{ backtest_id: string }>(`/employees/${emp.id}/backtest`), {
    success: 'Backtest started', onDone: (r) => setStarted(r.backtest_id),
  })
  const runBtn = <Act perm="backtest.run" variant="primary" icon={FlaskConical} loading={run.isPending || bt.data?.status === 'running'} onClick={() => run.mutate()}>Run backtest</Act>
  return (
    <div className="space-y-5">
      <div className="flex items-start gap-4">
        <div className="flex-1">
          <h2 className="text-base font-semibold">Backtest against last month</h2>
          <p className="text-sm text-muted">Replays labelled historical cases in Shadow mode and scores routes and issues against ground truth — before {emp.name} touches real work.</p>
        </div>
        {runBtn}
      </div>
      <Load q={list}>{() => !id ? <Panel><Empty icon={FlaskConical} title="No backtest yet" body={`Run one to measure ${emp.name}’s accuracy. Promotion out of Shadow depends on it.`} action={runBtn} /></Panel>
        : <Load q={bt}>{(b) => <BacktestResult b={b} history={history} onPick={setStarted} />}</Load>}
      </Load>
    </div>
  )
}

function BacktestResult({ b, history, onPick }: { b: Backtest; history: Backtest[]; onPick: (id: string) => void }) {
  const [only, setOnly] = useState<'all' | 'miss'>('all')
  const rows = (b.rows ?? []).filter((r) => only === 'all' || !r.correct || r.expected_issues.join() !== r.found_issues.join())
  if (b.status === 'running') return (
    <Panel className="p-5">
      <div className="mb-2 flex justify-between text-sm"><span className="font-medium">Replaying cases…</span><span className="text-muted tnum">{pct(b.progress)}</span></div>
      <Meter value={b.progress} />
    </Panel>
  )
  const acc = b.route_accuracy
  return (
    <>
      <Panel className="grid grid-cols-3 divide-x divide-line md:grid-cols-6">
        <Stat label="Route accuracy" value={<span className={cn(acc != null && (acc >= 0.9 ? 'text-ok' : acc >= 0.85 ? 'text-warn' : 'text-bad'))}>{pct(acc, 1)}</span>} hint={`plan v${b.plan_version ?? '—'}`} />
        <Stat label="Cases replayed" value={num(b.n_tasks)} hint={b.status === 'error' ? 'ended with an error' : 'with ground truth'} />
        <Stat label="Hours saved" value={num(b.hours_saved, 1)} hint="if run for real" />
        <Stat label="Cost saved" value={inrShort(b.money_saved_inr)} />
        <Stat label="AI calls" value={num(b.ai_calls)} hint={`${num(b.ai_calls / Math.max(1, b.n_tasks), 1)} per case`} />
        <Stat label="Duration" value={`${num(b.duration_s, 1)}s`} hint={ago(b.created_at)} />
      </Panel>
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
        <Panel className="xl:col-span-2">
          <PanelHead title="Issue detection" hint="Precision = flags that were right · Recall = planted issues that were caught" />
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-subtle"><tr className="border-b border-line">
              <th className="px-4 py-2 font-medium">Issue type</th>{['TP', 'FP', 'FN'].map((h) => <th key={h} className="w-12 px-2 py-2 text-right font-medium">{h}</th>)}
              <th className="w-40 px-4 py-2 font-medium">Precision</th><th className="w-40 px-4 py-2 font-medium">Recall</th></tr></thead>
            <tbody className="divide-y divide-line">
              {b.per_issue.map((r) => (
                <tr key={r.type}>
                  <td className="px-4 py-2">{humanize(r.type)}</td>
                  <td className="px-2 py-2 text-right tnum">{r.tp}</td><td className={cn('px-2 py-2 text-right tnum', r.fp && 'text-bad')}>{r.fp}</td><td className={cn('px-2 py-2 text-right tnum', r.fn && 'text-bad')}>{r.fn}</td>
                  {[r.precision, r.recall].map((v, i) => (
                    <td key={i} className="px-4 py-2"><div className="flex items-center gap-2"><Meter value={v ?? 0} tone={v == null ? 'neutral' : v >= 0.9 ? 'ok' : 'warn'} /><span className="w-9 text-right text-xs tnum">{pct(v)}</span></div></td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <Panel>
          <PanelHead title="Runs" hint="Every backtest is kept for audit" />
          <ul className="max-h-80 divide-y divide-line overflow-y-auto">
            {history.map((h) => (
              <li key={h.id}><button onClick={() => onPick(h.id)} className={cn('flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-raised/50', h.id === b.id && 'bg-raised/70')}>
                <History className="size-3.5 text-subtle" />
                <div className="min-w-0 flex-1"><div className="text-sm">{stamp(h.created_at)}</div><Mono className="text-2xs">{h.id} · v{h.plan_version ?? '—'} · {h.n_tasks} cases</Mono></div>
                <span className="text-sm font-medium tnum">{pct(h.route_accuracy)}</span>
              </button></li>
            ))}
          </ul>
        </Panel>
      </div>
      <Panel>
        <PanelHead title="Expected vs predicted" hint={`${(b.rows ?? []).filter((r) => r.correct).length} of ${b.rows?.length ?? 0} routed correctly`}
          actions={<Segmented value={only} onChange={setOnly} options={[{ id: 'all', label: 'All cases' }, { id: 'miss', label: 'Differences only' }]} />} />
        {rows.length === 0 ? <Empty icon={CheckCircle2} title="No differences" body="Every case was routed and flagged exactly as labelled." /> : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-subtle"><tr className="border-b border-line">
              {['', 'Case', 'Subject', 'Amount', 'Expected route', 'Predicted route', 'Expected issues', 'Found issues'].map((h, i) => <th key={i} className={cn('px-3 py-2 font-medium', h === 'Amount' && 'text-right')}>{h}</th>)}</tr></thead>
            <tbody className="divide-y divide-line">
              {rows.map((r) => (
                <tr key={r.file} className={cn(!r.correct && 'bg-bad/5')}>
                  <td className="w-8 pl-4">{r.correct ? <Check className="size-4 text-ok" /> : <XCircle className="size-4 text-bad" />}</td>
                  <td className="px-3 py-2"><Mono>{r.file.replace(/^history\//, '')}</Mono></td>
                  <td className="max-w-64 truncate px-3 py-2">{r.vendor}</td>
                  <td className="px-3 py-2 text-right tnum">{r.total == null ? '—' : inr(r.total)}</td>
                  <td className="px-3 py-2"><Mono>{r.expected_route}</Mono></td>
                  <td className="px-3 py-2"><Mono className={cn(!r.correct && 'text-bad')}>{r.predicted_route}</Mono></td>
                  <td className="px-3 py-2">{issueChips(r.expected_issues, 'neutral')}</td>
                  <td className="px-3 py-2">{issueChips(r.found_issues, 'warn')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </>
  )
}

/* ================================================================== Autonomy */
const CRITERIA = ['Every new hire starts here', 'Backtest accuracy above the promotion threshold on enough cases', 'Higher accuracy plus supervised actions approved by a manager']

export function AutonomyTab({ emp }: { emp: Employee }) {
  const p = emp.promotion
  const level = emp.autonomy_level
  const promote = useAction((to: number) => api.post<Employee>(`/employees/${emp.id}/promote`, { level: to }), {
    success: (r) => `${emp.name} is now ${r.autonomy_label}`,
  })
  return (
    <div className="max-w-5xl space-y-5">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {AUTONOMY.map((a, i) => (
          <div key={a.label} className={cn('relative rounded-lg border bg-panel p-4', i === level ? 'border-accent ring-2 ring-accent/20' : 'border-line', i > level && 'opacity-70')}>
            <div className="flex items-center gap-2">
              <span className={cn('flex size-6 items-center justify-center rounded-full text-xs font-semibold', i <= level ? 'bg-accent-strong text-accent-fg' : 'bg-raised text-subtle')}>
                {i < level ? <Check className="size-3.5" /> : i}</span>
              <span className="font-semibold">{a.label}</span>
              {i === level && <Pill tone="accent" className="ml-auto">Current</Pill>}
            </div>
            <p className="mt-2 text-sm text-muted">{a.blurb}</p>
            <p className="mt-3 border-t border-line pt-2 text-xs text-subtle">Requires: {CRITERIA[i]}</p>
          </div>
        ))}
      </div>
      <Panel>
        <PanelHead title="Promotion" hint="Autonomy is earned from measured accuracy, never granted by default" />
        <div className="grid grid-cols-1 gap-6 p-4 md:grid-cols-2">
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              {p.next_level == null ? <Pill tone="ok" icon={Sparkles}>Top level reached</Pill>
                : p.eligible ? <Pill tone="ok" icon={CheckCircle2}>Eligible for {AUTONOMY[p.next_level].label}</Pill>
                : <Pill tone="warn">Not yet eligible for {AUTONOMY[p.next_level].label}</Pill>}
            </div>
            <p className="text-sm text-muted">{p.reason}</p>
            <div className="flex gap-2 pt-1">
              {p.next_level != null && (
                <Tip text={p.eligible ? `Promote to ${AUTONOMY[p.next_level].label}` : p.reason}>
                  <Act perm="employee.promote" variant="primary" icon={TrendingUp} disabled={!p.eligible} loading={promote.isPending}
                    onClick={() => promote.mutate(p.next_level!)}>Promote to {AUTONOMY[p.next_level].label}</Act>
                </Tip>
              )}
              {level > 0 && <Act perm="employee.promote" icon={TrendingDown} onClick={() => promote.mutate(level - 1)}>Move back to {AUTONOMY[level - 1].label}</Act>}
            </div>
          </div>
          <div className="space-y-4">
            <div>
              <div className="mb-1.5 flex justify-between text-xs"><span className="text-muted">Backtest accuracy</span><span className="tnum"><b className="text-fg">{pct(p.accuracy, 1)}</b> <span className="text-subtle">/ {pct(p.threshold)} needed</span></span></div>
              <div className="relative"><Meter value={p.accuracy ?? 0} tone={(p.accuracy ?? 0) >= p.threshold ? 'ok' : 'warn'} />
                <span className="absolute -top-1 h-3.5 w-px bg-fg" style={{ left: `${p.threshold * 100}%` }} /></div>
            </div>
            <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line">
              <div className="bg-panel px-3 py-2"><dt className="text-xs text-subtle">Backtest sample</dt><dd className="text-base font-semibold tnum">{p.sample_size} <span className="text-xs font-normal text-subtle">cases</span></dd></div>
              <div className="bg-panel px-3 py-2"><dt className="text-xs text-subtle">Supervised actions approved</dt><dd className="text-base font-semibold tnum">{emp.supervised_approvals ?? 0}</dd></div>
            </dl>
          </div>
        </div>
      </Panel>
    </div>
  )
}

/* ================================================================== Learning */
export function LearningTab({ emp }: { emp: Employee }) {
  // Learning applies to plans with a learned classification step (e.g. expense categorisation).
  const applies = emp.plan.steps.some((s) => s.action === 'classify_expense')
  const l = useLearning(applies ? emp.id : undefined)
  const train = useAction(() => api.post<{ cv_accuracy: number | null }>(`/learning/${emp.id}/train`), {
    success: (r) => `Model trained${r.cv_accuracy != null ? ` · CV accuracy ${pct(r.cv_accuracy)}` : ''}`,
  })
  if (!applies) return (
    <Panel className="max-w-3xl"><Empty icon={Brain} title="n/a for this role"
      body={`${emp.name} decides with the SOP’s rules and decision table, so there is no category model to train. Learning from corrections applies to employees whose workflow has a learned classification step, such as accounts-payable expense categorisation.`} /></Panel>
  )
  return (
    <Load q={l}>{(d) => (
      <div className="max-w-5xl space-y-5">
        <div className="flex items-start gap-4">
          <div className="flex-1">
            <h2 className="text-base font-semibold">Learns from your corrections</h2>
            <p className="text-sm text-muted">Fix a category on a case, then train. A small local model ({d.method}) takes over confident cases, so fewer calls go to Gemma.</p>
          </div>
          <Act perm="learning.train" variant="primary" icon={Brain} loading={train.isPending} onClick={() => train.mutate()}>Train now</Act>
        </div>
        <Panel className="grid grid-cols-2 divide-x divide-line md:grid-cols-5">
          <Stat label="Model" value={d.model_trained ? 'Trained' : 'Untrained'} hint={d.last_trained_at ? `trained ${ago(d.last_trained_at)}` : 'never trained'} />
          <Stat label="Training examples" value={num(d.n_examples)} hint="past bookings + corrections" />
          <Stat label="Corrections" value={num(d.n_corrections)} hint="from reviewers" />
          <Stat label="CV accuracy" value={pct(d.cv_accuracy, 1)} hint="5-fold cross-validation" />
          <Stat label="AI calls saved" value={num(d.ai_calls_saved)} hint="handled locally" />
        </Panel>
        <Panel className="p-4">
          <div className="mb-2 text-xs font-medium text-muted">Labels the model predicts</div>
          <div className="flex flex-wrap gap-1.5">{d.labels.map((x) => <Pill key={x}>{x}</Pill>)}</div>
          <ol className="mt-4 flex flex-wrap items-center gap-2 text-xs text-muted">
            {['Open a case in the Work queue', 'Correct its category', 'Train here', 'AI calls per case drop on the Overview'].map((s, i) => (
              <li key={s} className="flex items-center gap-2">{i > 0 && <ArrowRight className="size-3 text-subtle" />}<span className="rounded border border-line bg-sunken px-2 py-1">{i + 1}. {s}</span></li>
            ))}
          </ol>
          <Link to={`/work?employee=${emp.id}`} className="mt-3 inline-block text-sm text-accent hover:underline">Open {emp.name}’s cases →</Link>
        </Panel>
      </div>
    )}</Load>
  )
}

/* ================================================================== Versions */
const show = (v: unknown) => (v === undefined ? '—' : typeof v === 'string' ? v : JSON.stringify(v))

export function VersionsTab({ emp }: { emp: Employee }) {
  const vs = useVersions(emp.id)
  const list = [...(vs.data ?? [])].sort((a, b) => b.version - a.version)
  const [pair, setPair] = useState<[number | null, number | null]>([null, null])
  const b = pair[1] ?? list[0]?.version ?? null
  const a = pair[0] ?? list[1]?.version ?? null
  const diff = useDiff(emp.id, a, b)
  return (
    <Load q={vs}>{() => list.length < 2 ? (
      <Panel className="max-w-3xl"><Empty icon={GitCompare} title={`Only v${list[0]?.version ?? 1} exists`} body="Edit a step in the Workflow tab and save — every save passes the checker and becomes a new, diffable version." /></Panel>
    ) : (
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
        <Panel>
          <PanelHead title="Versions" hint="Pick A (base) and B (compare)" />
          <ul className="divide-y divide-line">
            {list.map((v) => (
              <li key={v.version} className="flex items-center gap-3 px-4 py-2.5">
                <span className="font-mono text-sm font-medium">v{v.version}</span>
                <div className="min-w-0 flex-1"><div className="truncate text-sm">{v.note}</div><div className="text-xs text-subtle">{stamp(v.created_at)}</div></div>
                {(['A', 'B'] as const).map((k, i) => {
                  const on = (i === 0 ? a : b) === v.version
                  return <button key={k} onClick={() => setPair(i === 0 ? [v.version, b] : [a, v.version])}
                    className={cn('size-6 rounded border text-2xs font-semibold', on ? 'border-accent bg-accent/15 text-accent' : 'border-line text-subtle hover:text-fg')}>{k}</button>
                })}
              </li>
            ))}
          </ul>
        </Panel>
        <Panel className="xl:col-span-2">
          <PanelHead title={<span className="font-mono">v{a} → v{b}</span>} hint={diff.data ? `${diff.data.changes.length} change(s)` : ' '} />
          {a === b ? <Empty icon={GitCompare} title="Pick two different versions" /> : (
            <Load q={diff}>{(d) => d.changes.length === 0 ? <Empty icon={GitCompare} title="No differences" /> : (
              <table className="w-full table-fixed text-sm">
                <thead className="text-left text-xs text-subtle"><tr className="border-b border-line">
                  <th className="w-20 px-4 py-2 font-medium">Step</th><th className="w-24 px-2 py-2 font-medium">Change</th><th className="w-28 px-2 py-2 font-medium">Field</th><th className="px-2 py-2 font-medium">Before</th><th className="px-4 py-2 font-medium">After</th></tr></thead>
                <tbody className="divide-y divide-line">
                  {d.changes.map((c, i) => (
                    <tr key={i} className="align-top">
                      <td className="px-4 py-2"><Mono>{c.step_id}</Mono></td>
                      <td className="px-2 py-2"><Pill tone={c.kind === 'added' ? 'ok' : c.kind === 'removed' ? 'bad' : 'accent'}>{c.kind}</Pill></td>
                      <td className="px-2 py-2"><Mono>{c.field ?? '—'}</Mono></td>
                      <td className="px-2 py-2"><code className="block rounded bg-bad/10 px-1.5 py-0.5 font-mono text-2xs break-all text-bad line-through decoration-bad/40">{show(c.before)}</code></td>
                      <td className="px-4 py-2"><code className="block rounded bg-ok/10 px-1.5 py-0.5 font-mono text-2xs break-all text-ok">{show(c.after)}</code></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}</Load>
          )}
        </Panel>
      </div>
    )}</Load>
  )
}
