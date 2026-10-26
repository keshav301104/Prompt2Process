import { Fragment, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bot, ChevronRight, Download, FileOutput, ScrollText, Search, UserRound } from 'lucide-react'
import { useAudit, useEmployees, useOutputs, type AuditRow, type Employee, type Output } from '../lib/api'
import { cn, humanize, shortId, stamp } from '../lib/format'
import { Avatar, Button, Empty, Input, Load, Mono, PageHeader, Pill, Segmented, Select, Skeleton, Tabs } from '../components/ui'

const csv = (rows: (string | number | null | undefined)[][]) =>
  rows.map((r) => r.map((c) => `"${String(c ?? '').replace(/"/g, '""')}"`).join(',')).join('\n')
function download(name: string, text: string) {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob([text], { type: 'text/csv' }))
  a.download = name
  a.click()
  URL.revokeObjectURL(a.href)
}

export function AuditPage() {
  const [tab, setTab] = useState<'log' | 'outputs'>('log')
  const audit = useAudit()
  const outputs = useOutputs()
  const emps = useEmployees()
  const byName = new Map((emps.data ?? []).map((e) => [e.name, e]))
  const byId = new Map((emps.data ?? []).map((e) => [e.id, e]))
  return (
    <div>
      <PageHeader title="Audit" subtitle="Append-only record of every decision, action and artefact — by people and by digital employees.">
        <Tabs value={tab} onChange={setTab} tabs={[{ id: 'log', label: 'Audit log', icon: ScrollText, count: audit.data?.length }, { id: 'outputs', label: 'Outputs', icon: FileOutput, count: outputs.data?.length }]} />
      </PageHeader>
      <div className="p-6">
        {tab === 'log'
          ? <Load q={audit} skeleton={<Skeleton className="h-96" />}>{(rows) => <AuditLog rows={rows} byName={byName} />}</Load>
          : <Load q={outputs} skeleton={<Skeleton className="h-96" />}>{(rows) => <Outputs rows={rows} byId={byId} />}</Load>}
      </div>
    </div>
  )
}

function Actor({ name, emp }: { name: string; emp?: Employee }) {
  return emp
    ? <span className="flex items-center gap-1.5"><Avatar emp={emp} size="sm" />{name}<Bot className="size-3 text-subtle" /></span>
    : <span className="flex items-center gap-1.5"><span className="flex size-5 items-center justify-center rounded-md bg-raised"><UserRound className="size-3 text-muted" /></span>{humanize(name)}</span>
}

function AuditLog({ rows, byName }: { rows: AuditRow[]; byName: Map<string, Employee> }) {
  const [q, setQ] = useState('')
  const [actor, setActor] = useState('')
  const [action, setAction] = useState('')
  const actors = [...new Set(rows.map((r) => r.actor))].sort()
  const actions = [...new Set(rows.map((r) => r.action))].sort()
  const list = rows.filter((r) => (!actor || r.actor === actor) && (!action || r.action === action)
    && (!q || `${r.detail} ${r.task_id ?? ''}`.toLowerCase().includes(q.toLowerCase())))
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-panel">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2.5">
        <div className="relative w-72"><Search className="pointer-events-none absolute top-2 left-2.5 size-4 text-subtle" />
          <Input className="pl-8" placeholder="Search details or case ids" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <Select className="w-44" value={actor} onChange={(e) => setActor(e.target.value)}><option value="">All actors</option>{actors.map((a) => <option key={a}>{a}</option>)}</Select>
        <Select className="w-48" value={action} onChange={(e) => setAction(e.target.value)}><option value="">All actions</option>{actions.map((a) => <option key={a}>{a}</option>)}</Select>
        <span className="ml-auto text-xs text-subtle">{list.length} of {rows.length} entries</span>
        <Button size="sm" icon={Download} onClick={() => download('prompt2process-audit.csv', csv([['timestamp', 'actor', 'action', 'task_id', 'detail'], ...list.map((r) => [r.ts, r.actor, r.action, r.task_id, r.detail])]))}>Export CSV</Button>
      </div>
      {list.length === 0 ? <Empty icon={ScrollText} title={rows.length ? 'No entries match' : 'Nothing audited yet'} body="Hires, runs, approvals and every side effect are recorded here." /> : (
        <table className="w-full text-sm">
          <thead className="border-b border-line bg-sunken text-left text-xs text-subtle"><tr>{['Time', 'Actor', 'Action', 'Detail', 'Case'].map((h) => <th key={h} className="px-4 py-2 font-medium">{h}</th>)}</tr></thead>
          <tbody className="divide-y divide-line">
            {list.map((r, i) => (
              <tr key={i} className="align-top hover:bg-raised/40">
                <td className="px-4 py-2 font-mono text-xs whitespace-nowrap text-muted">{stamp(r.ts)}</td>
                <td className="px-4 py-2 whitespace-nowrap"><Actor name={r.actor} emp={byName.get(r.actor)} /></td>
                <td className="px-4 py-2"><span className="rounded border border-line bg-sunken px-1.5 py-0.5 font-mono text-2xs whitespace-nowrap text-muted">{r.action}</span></td>
                <td className="px-4 py-2 text-muted">{r.detail}</td>
                <td className="px-4 py-2">{r.task_id ? <Link to={`/work/${r.task_id}`} className="font-mono text-xs text-accent hover:underline">{shortId(r.task_id)}</Link> : <span className="text-subtle">—</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

const KIND_TONE: Record<string, 'accent' | 'ok' | 'warn' | 'bad' | 'neutral'> = { payment: 'warn', journal: 'accent', rejection: 'bad', decision: 'ok', email: 'neutral' }

function Outputs({ rows, byId }: { rows: Output[]; byId: Map<string, Employee> }) {
  const [kind, setKind] = useState('all')
  const [open, setOpen] = useState<string | null>(null)
  const kinds = [...new Set(rows.map((r) => r.kind))].sort()
  const list = rows.filter((r) => kind === 'all' || r.kind === kind)
  if (!rows.length) return <Empty icon={FileOutput} title="No outputs yet" body="Emails, journal entries, payments and decisions produced by employees appear here." />
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-panel">
      <div className="flex items-center gap-2 border-b border-line px-3 py-2.5">
        <Segmented value={kind} onChange={setKind} options={[{ id: 'all', label: 'All' }, ...kinds.map((k) => ({ id: k, label: humanize(k) }))]} />
        <span className="ml-auto text-xs text-subtle">{list.length} outputs</span>
        <Button size="sm" icon={Download} onClick={() => download('prompt2process-outputs.csv', csv([['created_at', 'kind', 'employee', 'task_id', 'summary'], ...list.map((r) => [r.created_at, r.kind, byId.get(r.employee_id)?.name, r.task_id, r.data.summary])]))}>Export CSV</Button>
      </div>
      <table className="w-full text-sm">
        <thead className="border-b border-line bg-sunken text-left text-xs text-subtle"><tr><th className="w-8" />{['Time', 'Kind', 'Employee', 'Summary', 'Case'].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
        <tbody className="divide-y divide-line">
          {list.map((r) => {
            const e = byId.get(r.employee_id)
            const isOpen = open === r.id
            return (
              <Fragment key={r.id}>
                <tr onClick={() => setOpen(isOpen ? null : r.id)} className="cursor-pointer hover:bg-raised/40">
                  <td className="pl-3"><ChevronRight className={cn('size-3.5 text-subtle transition-transform', isOpen && 'rotate-90')} /></td>
                  <td className="px-3 py-2 font-mono text-xs whitespace-nowrap text-muted">{stamp(r.created_at)}</td>
                  <td className="px-3 py-2"><Pill tone={KIND_TONE[r.kind] ?? 'neutral'}>{humanize(r.kind)}</Pill></td>
                  <td className="px-3 py-2 whitespace-nowrap">{e ? <span className="flex items-center gap-1.5"><Avatar emp={e} size="sm" />{e.name}</span> : <Mono>{r.employee_id}</Mono>}</td>
                  <td className="max-w-xl truncate px-3 py-2">{r.data.summary ?? '—'}</td>
                  <td className="px-3 py-2">{r.task_id && <Link onClick={(ev) => ev.stopPropagation()} to={`/work/${r.task_id}`} className="font-mono text-xs text-accent hover:underline">{shortId(r.task_id)}</Link>}</td>
                </tr>
                {isOpen && (
                  <tr className="bg-sunken/60"><td />
                    <td colSpan={5} className="px-3 py-3">
                      {r.data.body ? (
                        <div className="max-w-3xl rounded-md border border-line bg-panel">
                          <div className="border-b border-line px-3.5 py-2 text-xs text-muted">To <b className="text-fg">{String(r.data.to ?? '—')}</b> · {String(r.data.subject ?? '')}</div>
                          <p className="px-3.5 py-3 text-sm leading-relaxed whitespace-pre-wrap">{String(r.data.body)}</p>
                        </div>
                      ) : (
                        <dl className="grid max-w-3xl grid-cols-[160px_1fr] gap-x-4 gap-y-1 text-xs">
                          {Object.entries(r.data).filter(([k]) => k !== 'summary').map(([k, v]) => (
                            <Fragment key={k}><dt className="text-subtle">{humanize(k)}</dt><dd className="font-mono break-all text-muted">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</dd></Fragment>
                          ))}
                        </dl>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
