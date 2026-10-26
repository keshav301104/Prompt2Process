import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { AlertOctagon, AlertTriangle, ArrowUpRight, Check, CheckCheck, Eye, Info, ShieldCheck, Wrench, X, type LucideIcon } from 'lucide-react'
import { api, useAction, useDecided, useEmployees, useInbox, useLearning, useSession, type Employee, type Field, type Flag, type InboxItem } from '../lib/api'
import { ago, cn, fieldLabel, humanize, inr, isMoneyField, stamp } from '../lib/format'
import { CheckReportView } from '../components/plan-graph'
import { Act, Avatar, Empty, Kbd, Label, Load, Mono, PageHeader, Pill, Segmented, Select, Skeleton, Tabs, Textarea } from '../components/ui'

const KIND: Record<InboxItem['kind'], { label: string; icon: LucideIcon; tone: 'accent' | 'warn' | 'ok'; cls: string }> = {
  approval: { label: 'Approval', icon: ShieldCheck, tone: 'accent', cls: 'text-accent' },
  review: { label: 'Review', icon: Eye, tone: 'warn', cls: 'text-warn' },
  healing: { label: 'Self-healing', icon: Wrench, tone: 'ok', cls: 'text-ok' },
}

export function InboxPage() {
  const [tab, setTab] = useState<'open' | 'decided'>('open')
  const [kind, setKind] = useState<'all' | InboxItem['kind']>('all')
  const open = useInbox()
  const decided = useDecided()
  const emps = useEmployees()
  const empById = new Map((emps.data ?? []).map((e) => [e.id, e]))
  return (
    <div className="flex h-full flex-col">
      <PageHeader title="Inbox" subtitle="Approvals, reviews and self-healing fixes waiting on a human. Every decision is audited.">
        <div className="flex items-end justify-between">
          <Tabs value={tab} onChange={setTab} tabs={[{ id: 'open', label: 'Open', count: open.data?.length }, { id: 'decided', label: 'Decided', count: decided.data?.length }]} />
          {tab === 'open' && <div className="pb-1.5"><Segmented value={kind} onChange={setKind} options={[{ id: 'all', label: 'All' }, { id: 'approval', label: 'Approvals' }, { id: 'review', label: 'Reviews' }, { id: 'healing', label: 'Self-healing' }]} /></div>}
        </div>
      </PageHeader>
      <div className="min-h-0 flex-1">
        {tab === 'open'
          ? <Load q={open} skeleton={<div className="space-y-2 p-6">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-16" />)}</div>}>
            {(items) => <OpenInbox items={items.filter((i) => kind === 'all' || i.kind === kind)} empById={empById} />}
          </Load>
          : <div className="h-full overflow-auto p-6"><Load q={decided}>{(items) => <DecidedTable items={items} empById={empById} />}</Load></div>}
      </div>
    </div>
  )
}

function OpenInbox({ items, empById }: { items: InboxItem[]; empById: Map<string, Employee> }) {
  const [sel, setSel] = useState<string | null>(null)
  const current = items.find((i) => i.id === sel) ?? items[0]
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest('input,textarea,select') || e.metaKey || e.ctrlKey) return
      const i = items.findIndex((x) => x.id === current?.id)
      if (e.key === 'j' || e.key === 'ArrowDown') { e.preventDefault(); setSel(items[Math.min(items.length - 1, i + 1)]?.id ?? null) }
      if (e.key === 'k' || e.key === 'ArrowUp') { e.preventDefault(); setSel(items[Math.max(0, i - 1)]?.id ?? null) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [items, current?.id])
  if (!items.length) return <Empty icon={CheckCheck} title="Inbox zero" body="Nothing is waiting on a human right now. New approvals and reviews appear here live." className="h-full" />
  const next = () => { const i = items.findIndex((x) => x.id === current?.id); setSel(items[i + 1]?.id ?? items[i - 1]?.id ?? null) }
  return (
    <div className="flex h-full">
      <ul className="w-[380px] shrink-0 divide-y divide-line overflow-y-auto border-r border-line bg-panel/40">
        {items.map((i) => {
          const k = KIND[i.kind]
          const e = empById.get(i.employee_id)
          return (
            <li key={i.id}>
              <button onClick={() => setSel(i.id)} className={cn('relative flex w-full gap-3 px-4 py-3 text-left hover:bg-raised/50', current?.id === i.id && 'bg-raised')}>
                {current?.id === i.id && <span className="absolute inset-y-0 left-0 w-0.5 bg-accent" />}
                <k.icon className={cn('mt-0.5 size-4 shrink-0', k.cls)} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2"><span className="truncate text-sm font-medium">{i.title}</span><span className="ml-auto shrink-0 text-2xs text-subtle">{ago(i.created_at)}</span></div>
                  <p className="truncate text-xs text-muted">{i.reason}</p>
                  {e && <div className="mt-1 flex items-center gap-1.5 text-xs text-subtle"><Avatar emp={e} size="sm" />{e.name} · {k.label}</div>}
                </div>
              </button>
            </li>
          )
        })}
      </ul>
      <div className="min-w-0 flex-1 overflow-y-auto">{current && <Detail key={current.id} item={current} emp={empById.get(current.employee_id)} onDone={next} />}</div>
    </div>
  )
}

function Detail({ item, emp, onDone }: { item: InboxItem; emp?: Employee; onDone: () => void }) {
  const [note, setNote] = useState('')
  const [category, setCategory] = useState<string>((item.payload.fields?.category?.value as string) ?? '')
  const { can } = useSession()
  const k = KIND[item.kind]
  const original = item.payload.fields?.category?.value
  const decide = useAction((decision: 'approve' | 'reject') => api.post(`/inbox/${item.id}/decide`, {
    decision, note: note || undefined, edits: item.kind === 'review' && category && category !== original ? { category } : undefined,
  }), { success: (_, d) => (d === 'approve' ? 'Approved — the employee resumes' : 'Rejected'), onDone })
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest('input,textarea,select') || e.metaKey || e.ctrlKey || decide.isPending || !can('inbox.decide')) return
      if (e.key === 'a') decide.mutate('approve')
      if (e.key === 'r') decide.mutate('reject')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [decide, can])

  return (
    <div className="mx-auto max-w-3xl space-y-5 p-6">
      <div>
        <div className="flex items-center gap-2"><Pill tone={k.tone} icon={k.icon}>{k.label}</Pill><span className="text-xs text-subtle">{stamp(item.created_at)}</span>
          {item.task_id && <Link to={`/work/${item.task_id}`} className="ml-auto flex items-center gap-1 text-xs text-accent hover:underline">Open case <ArrowUpRight className="size-3" /></Link>}</div>
        <h2 className="mt-2 text-lg font-semibold tracking-tight">{item.title}</h2>
        {emp && <div className="mt-1 flex items-center gap-1.5 text-sm text-muted"><Avatar emp={emp} size="sm" />{emp.name} · {emp.role_title ?? emp.role} · {emp.autonomy_label}</div>}
      </div>
      <p className="rounded-md border border-line bg-panel px-3.5 py-2.5 text-sm">{item.reason}</p>

      {item.kind === 'approval' && <ApprovalBody p={item.payload} />}
      {item.kind === 'review' && <ReviewBody p={item.payload} emp={emp} category={category} setCategory={setCategory} />}
      {item.kind === 'healing' && <HealingBody p={item.payload} />}

      <div className="sticky bottom-0 -mx-6 border-t border-line bg-canvas/95 px-6 py-4 backdrop-blur">
        <Textarea rows={2} placeholder="Add a note for the audit trail (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
        <div className="mt-3 flex items-center gap-2">
          <span className="mr-auto flex items-center gap-1.5 text-xs text-subtle"><Kbd>j</Kbd><Kbd>k</Kbd> move · <Kbd>a</Kbd> approve · <Kbd>r</Kbd> reject</span>
          <Act perm="inbox.decide" variant="danger" icon={X} loading={decide.isPending && decide.variables === 'reject'} onClick={() => decide.mutate('reject')}>Reject</Act>
          <Act perm="inbox.decide" variant="primary" icon={Check} loading={decide.isPending && decide.variables === 'approve'} onClick={() => decide.mutate('approve')}>
            {item.kind === 'healing' ? 'Apply fix' : item.kind === 'review' ? 'Approve & continue' : 'Approve'}</Act>
        </div>
      </div>
    </div>
  )
}

const Facts = ({ rows }: { rows: [string, ReactNode][] }) => (
  <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line">
    {rows.map(([l, v]) => <div key={l} className="bg-panel px-3.5 py-2.5"><dt className="text-xs text-subtle">{l}</dt><dd className="mt-0.5 text-sm break-words">{v}</dd></div>)}
  </dl>
)

function ApprovalBody({ p }: { p: Record<string, any> }) {
  return (
    <>
      {p.amount != null && <div><div className="text-xs text-subtle">Amount</div><div className="text-3xl font-semibold tracking-tight tnum">{inr(Number(p.amount))}</div></div>}
      <Facts rows={[
        ['Counterparty', p.vendor ?? '—'], ['Step', <span key="s">{p.step_title} <Mono>{p.step_id}</Mono></span>],
        ['Action', <Mono key="a" className="text-fg">{p.action ?? '—'}</Mono>],
        ['Approvers', <div key="ap" className="flex flex-wrap gap-1">{(p.approvers ?? []).map((a: string) => <Pill key={a}>{a}</Pill>)}</div>],
      ]} />
      {Array.isArray(p.covers) && p.covers.length > 0 && (
        <div className="rounded-md border border-line bg-panel">
          <div className="border-b border-line px-3.5 py-2 text-xs font-medium text-muted">This sign-off covers {p.covers.length} action{p.covers.length === 1 ? '' : 's'} on the case</div>
          <ul className="divide-y divide-line">{p.covers.map((c: string, i: number) => (
            <li key={c} className="flex items-center gap-2.5 px-3.5 py-2 text-sm"><span className="flex size-4 items-center justify-center rounded border border-accent/50 bg-accent/10 text-accent"><Check className="size-3" /></span>
              {c}<Mono className="ml-auto text-2xs text-subtle">{i + 1}/{p.covers.length}</Mono></li>))}</ul>
        </div>
      )}
      {p.supervised && <p className="text-xs text-muted">This employee is <b className="text-fg">Supervised</b>: one sign-off covers this case’s actions. Approvals count toward promotion to Autonomous.</p>}
      {p.params_preview && <details className="rounded-md border border-line bg-panel"><summary className="cursor-pointer px-3.5 py-2 text-xs text-muted">What will be executed</summary>
        <pre className="max-h-64 overflow-auto border-t border-line p-3.5 font-mono text-2xs leading-4 whitespace-pre-wrap text-muted">{p.params_preview}</pre></details>}
    </>
  )
}

const SEV = { critical: [AlertOctagon, 'text-bad'], warn: [AlertTriangle, 'text-warn'], info: [Info, 'text-muted'] } as const

function ReviewBody({ p, emp, category, setCategory }: { p: Record<string, any>; emp?: Employee; category: string; setCategory: (v: string) => void }) {
  const flags: Flag[] = p.flags ?? []
  const fields = Object.entries((p.fields ?? {}) as Record<string, Field>).filter(([k, f]) => k !== 'line_items' && typeof f?.value !== 'object').slice(0, 12)
  const isAp = !!p.fields?.category // the category can be corrected (and teaches the model)
  const l = useLearning(isAp ? emp?.id : undefined)
  return (
    <>
      {p.suggested_decision && <div className="rounded-md border border-accent/30 bg-accent/5 px-3.5 py-2.5 text-sm"><span className="font-medium text-accent">Suggested: </span>{p.suggested_decision}</div>}
      {flags.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold">Evidence</h3>
          {flags.map((f, i) => {
            const [Icon, cls] = SEV[f.severity] ?? SEV.info
            return (
              <div key={i} className="rounded-md border border-line bg-panel p-3">
                <div className="flex items-center gap-1.5 text-sm font-medium"><Icon className={cn('size-3.5', cls)} />{humanize(f.type)}<Pill className="ml-auto">{f.severity}</Pill></div>
                <p className="mt-1 text-sm text-muted">{f.message}</p>
                {f.evidence && <blockquote className="mt-2 rounded border-l-2 border-warn/60 bg-sunken px-2.5 py-1.5 font-mono text-xs break-words text-muted">{f.evidence}</blockquote>}
              </div>
            )
          })}
        </div>
      )}
      {fields.length > 0 && <Facts rows={fields.map(([k, f]) => [fieldLabel(k), typeof f.value === 'number' && isMoneyField(k) ? inr(f.value) : String(f.value ?? '—')])} />}
      {isAp && (
        <div className="max-w-xs"><Label hint="teaches the model">Category</Label>
          <Select value={category} onChange={(e) => setCategory(e.target.value)}>
            {[...new Set([category, ...(l.data?.labels ?? [])])].filter(Boolean).map((c) => <option key={c}>{c}</option>)}
          </Select></div>
      )}
    </>
  )
}

function HealingBody({ p }: { p: Record<string, any> }) {
  const patch: { step_id: string; field: string; before: unknown; after: unknown }[] = p.patch ?? []
  return (
    <>
      {p.error && <pre className="rounded-md border border-bad/30 bg-bad/5 p-3 font-mono text-xs whitespace-pre-wrap text-bad">{p.error}</pre>}
      {p.explanation && <div><h3 className="mb-1 text-sm font-semibold">Diagnosis</h3><p className="text-sm text-muted">{p.explanation}</p></div>}
      {patch.length > 0 && (
        <div className="overflow-hidden rounded-md border border-line">
          <div className="border-b border-line bg-sunken px-3.5 py-2 text-xs font-medium text-muted">Proposed patch · bounded to retries, fallbacks and guards</div>
          {patch.map((c, i) => (
            <div key={i} className="grid grid-cols-[80px_120px_1fr_1fr] items-start gap-3 border-b border-line px-3.5 py-2 last:border-0">
              <Mono>{c.step_id}</Mono><Mono>{c.field}</Mono>
              <code className="rounded bg-bad/10 px-1.5 py-0.5 font-mono text-2xs break-all text-bad">{JSON.stringify(c.before)}</code>
              <code className="rounded bg-ok/10 px-1.5 py-0.5 font-mono text-2xs break-all text-ok">{JSON.stringify(c.after)}</code>
            </div>
          ))}
        </div>
      )}
      {p.check && <CheckReportView report={p.check} />}
    </>
  )
}

function DecidedTable({ items, empById }: { items: InboxItem[]; empById: Map<string, Employee> }) {
  if (!items.length) return <Empty icon={CheckCheck} title="No decisions yet" body="Approved and rejected items are kept here for the record." />
  const sorted = [...items].sort((a, b) => (b.decision?.at ?? '').localeCompare(a.decision?.at ?? ''))
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-panel">
      <table className="w-full text-sm">
        <thead className="border-b border-line bg-sunken text-left text-xs text-subtle"><tr>{['Decided', 'Item', 'Employee', 'Decision', 'By', 'Note'].map((h) => <th key={h} className="px-4 py-2 font-medium">{h}</th>)}</tr></thead>
        <tbody className="divide-y divide-line">
          {sorted.map((i) => {
            const e = empById.get(i.employee_id)
            const ok = i.decision?.decision === 'approve'
            return (
              <tr key={i.id}>
                <td className="px-4 py-2.5 font-mono text-xs whitespace-nowrap text-muted">{stamp(i.decision?.at)}</td>
                <td className="max-w-md px-4 py-2.5"><div className="flex items-center gap-2"><Pill tone={KIND[i.kind].tone}>{KIND[i.kind].label}</Pill>
                  {i.task_id ? <Link to={`/work/${i.task_id}`} className="truncate hover:underline">{i.title}</Link> : <span className="truncate">{i.title}</span>}</div></td>
                <td className="px-4 py-2.5">{e && <span className="flex items-center gap-1.5"><Avatar emp={e} size="sm" />{e.name}</span>}</td>
                <td className="px-4 py-2.5"><Pill tone={ok ? 'ok' : 'bad'} icon={ok ? Check : X}>{ok ? 'Approved' : 'Rejected'}</Pill></td>
                <td className="px-4 py-2.5 text-muted">{i.decision?.by}</td>
                <td className="px-4 py-2.5 text-muted"><div className="max-w-60 truncate" title={i.decision?.note}>{i.decision?.note || '—'}</div></td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
