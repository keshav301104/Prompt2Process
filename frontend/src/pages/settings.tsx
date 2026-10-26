import { useState, type ChangeEvent, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { Check, Cpu, Flame, IndianRupee, Minus, RotateCcw, Save, ScanText, Shield } from 'lucide-react'
import { api, useAction, useHealth, useOrg, useRoles, useSession, useSettings, useTrace, type Settings } from '../lib/api'
import { cn, num, PERMS, stamp } from '../lib/format'
import { Act, Empty, Input, Label, Load, Mono, PageHeader, Panel, PanelHead, Pill, Segmented, Skeleton, Switch } from '../components/ui'
import { OrgForm } from './setup'

type Econ = Pick<Settings, 'hourly_cost_inr' | 'minutes_per_invoice_manual' | 'minutes_per_collection_manual' | 'minutes_per_case_manual'>

export function SettingsPage() {
  const s = useSettings()
  const org = useOrg()
  return (
    <div>
      <PageHeader title="Settings" subtitle="Organisation, reliability, economics and the model behind every employee." />
      <div className="max-w-5xl space-y-5 p-6">
        <Load q={org} skeleton={<Skeleton className="h-64" />}>{(o) => <OrgForm initial={o} submitLabel="Save organisation" />}</Load>
        <Load q={s}>{(d) => <Controls s={d} />}</Load>
        <ModelPanel />
        <RolesMatrix />
        <DangerZone />
      </div>
    </div>
  )
}

const Row = ({ icon: Icon, title, body, children }: { icon: typeof Flame; title: string; body: string; children: ReactNode }) => (
  <div className="flex items-start gap-4 px-4 py-4">
    <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-line bg-raised"><Icon className="size-4 text-muted" /></span>
    <div className="min-w-0 flex-1"><div className="text-sm font-medium">{title}</div><p className="mt-0.5 text-xs text-muted">{body}</p></div>
    <div className="shrink-0">{children}</div>
  </div>
)

function Controls({ s }: { s: Settings }) {
  const { can } = useSession()
  const allowed = can('settings.edit')
  const [econ, setEcon] = useState<Econ>(s)
  const [drag, setDrag] = useState<number | null>(null) // slider value while dragging; server value otherwise
  const rate = drag ?? s.chaos_rate
  const commit = () => { if (drag != null && drag !== s.chaos_rate) put.mutate({ chaos_rate: drag }); setDrag(null) }
  const put = useAction((body: Partial<Settings>) => api.put<Settings>('/settings', body), { success: 'Settings saved' })
  const dirty = (Object.keys(econ) as (keyof Econ)[]).some((k) => econ[k] !== s[k])
  const num$ = (k: keyof Econ) => ({ type: 'number', min: 0, disabled: !allowed, value: econ[k] ?? 0, onChange: (e: ChangeEvent<HTMLInputElement>) => setEcon({ ...econ, [k]: Number(e.target.value) }) })
  return (
    <>
      <Panel>
        <PanelHead title="Reliability" hint="Prove the runtime recovers: retries, fallbacks, checkpoints and self-healing" />
        <div className="divide-y divide-line">
          <Row icon={Flame} title="Chaos mode" body="Randomly fail steps while employees work. Watch retries recover and hard failures turn into self-healing proposals in the inbox.">
            <Switch checked={s.chaos_mode} disabled={!allowed} onChange={(v) => put.mutate({ chaos_mode: v })} label="Chaos mode" />
          </Row>
          <Row icon={Flame} title="Failure rate" body="Probability that any single step attempt fails while chaos mode is on.">
            <div className="flex w-64 items-center gap-3">
              <input type="range" min={0} max={0.8} step={0.05} value={rate} disabled={!allowed} className="flex-1"
                onChange={(e) => setDrag(Number(e.target.value))} onPointerUp={commit} onKeyUp={commit} />
              <span className="w-10 text-right text-sm font-medium tnum">{Math.round(rate * 100)}%</span>
            </div>
          </Row>
          <Row icon={ScanText} title="Extraction strategy" body="Template-first reads known layouts deterministically and only calls Gemma when confidence is low. LLM-first always asks Gemma.">
            <Segmented value={s.extraction_mode} onChange={(v) => allowed && put.mutate({ extraction_mode: v })}
              options={[{ id: 'template_first', label: 'Template first' }, { id: 'llm_first', label: 'LLM first' }]} />
          </Row>
        </div>
      </Panel>
      <Panel>
        <PanelHead title="Economics" hint="Used for hours-saved and ₹-saved on every dashboard"
          actions={<Act perm="settings.edit" size="sm" variant="primary" icon={Save} disabled={!dirty} loading={put.isPending} onClick={() => put.mutate(econ)}>Save</Act>} />
        <div className="grid grid-cols-2 gap-4 p-4 md:grid-cols-4">
          <div><Label hint="₹ / hour">Clerk cost</Label><div className="relative"><IndianRupee className="pointer-events-none absolute top-2 left-2.5 size-3.5 text-subtle" /><Input className="pl-7" {...num$('hourly_cost_inr')} /></div></div>
          <div><Label hint="minutes">Manual invoice</Label><Input {...num$('minutes_per_invoice_manual')} /></div>
          <div><Label hint="minutes">Manual collection</Label><Input {...num$('minutes_per_collection_manual')} /></div>
          <div><Label hint="minutes">Manual case</Label><Input {...num$('minutes_per_case_manual')} /></div>
        </div>
      </Panel>
    </>
  )
}

function ModelPanel() {
  const h = useHealth()
  const tr = useTrace()
  const live = h.data?.llm_mode === 'live'
  return (
    <Panel>
      <PanelHead title="Gemma 4" hint="Open-weights model used as compiler and judge — every call is traced"
        actions={h.data && <Pill tone={live ? 'ok' : 'neutral'} dot pulse={live}>{live ? 'live' : 'offline'}</Pill>} />
      <dl className="grid grid-cols-2 divide-x divide-line border-b border-line md:grid-cols-4">
        {[['Mode', h.data?.llm_mode ?? '—'], ['Text model', h.data?.model ?? '—'], ['Vision model', h.data?.vision_model ?? '—'], ['Calls this session', num(tr.data?.total_calls)]].map(([l, v]) => (
          <div key={l} className="min-w-0 px-4 py-3"><dt className="text-xs text-subtle">{l}</dt><dd className="mt-0.5 truncate font-mono text-sm">{v}</dd></div>
        ))}
      </dl>
      {!live && h.data?.llm_error && <p className="border-b border-line px-4 py-2.5 text-xs text-muted">Offline: {h.data.llm_error}. Employees keep working on deterministic fallbacks.</p>}
      <Load q={tr}>{(t) => t.calls.length === 0 ? <Empty icon={Cpu} title="No model calls yet" body="Each Gemma call — purpose, size and latency — is listed here as employees work." /> : (
        <div className="max-h-96 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-sunken text-left text-xs text-subtle"><tr>{['Time', 'Purpose', 'Model', 'Prompt', 'Output', 'Latency'].map((x, i) => <th key={x} className={cn('px-4 py-2 font-medium', i >= 3 && 'text-right')}>{x}</th>)}</tr></thead>
            <tbody className="divide-y divide-line">
              {[...t.calls].reverse().map((c, i) => (
                <tr key={i}>
                  <td className="px-4 py-2 font-mono text-xs text-muted">{stamp(c.ts)}</td>
                  <td className="px-4 py-2">{c.purpose}{c.vision && <Pill tone="accent" className="ml-2">vision</Pill>}</td>
                  <td className="px-4 py-2"><Mono>{c.model}</Mono></td>
                  <td className="px-4 py-2 text-right tnum text-muted">{num(c.prompt_chars)}</td>
                  <td className="px-4 py-2 text-right tnum text-muted">{num(c.output_chars)}</td>
                  <td className="px-4 py-2 text-right tnum">{num(c.seconds, 1)}s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}</Load>
    </Panel>
  )
}

function RolesMatrix() {
  const roles = useRoles()
  const { role } = useSession()
  return (
    <Panel>
      <PanelHead title="Roles & permissions" hint="Enforced by the API; the console hides or disables what a role can’t do" actions={<Pill icon={Shield}>Viewing as {role.label}</Pill>} />
      <Load q={roles}>{(rs) => (
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-subtle"><tr className="border-b border-line"><th className="px-4 py-2 font-medium">Permission</th>{rs.map((r) => <th key={r.id} className={cn('px-2 py-2 text-center font-medium', r.id === role.id && 'text-accent')}>{r.label}</th>)}</tr></thead>
          <tbody className="divide-y divide-line">
            {Object.entries(PERMS).map(([perm, label]) => (
              <tr key={perm}>
                <td className="px-4 py-2"><span className="capitalize">{label}</span> <Mono className="ml-1 text-2xs text-subtle">{perm}</Mono></td>
                {rs.map((r) => {
                  const ok = r.can.includes('*') || r.can.includes(perm)
                  return <td key={r.id} className={cn('px-2 py-2 text-center', r.id === role.id && 'bg-accent/5')}>{ok ? <Check className="mx-auto size-4 text-ok" /> : <Minus className="mx-auto size-4 text-line-strong" />}</td>
                })}
              </tr>
            ))}
          </tbody>
        </table>
      )}</Load>
    </Panel>
  )
}

function DangerZone() {
  const [armed, setArmed] = useState(false)
  const nav = useNavigate()
  const reset = useAction(() => api.post('/workspace/reset'), { success: 'Workspace reset — starting fresh', onDone: () => nav('/') })
  return (
    <section className="rounded-lg border border-bad/40">
      <header className="border-b border-bad/30 px-4 py-2.5"><h3 className="text-sm font-semibold text-bad">Danger zone</h3></header>
      <div className="flex items-center gap-4 p-4">
        <div className="flex-1">
          <div className="text-sm font-medium">Reset workspace</div>
          <p className="text-xs text-muted">Removes the organisation profile, every digital employee, all work, inbox items and outputs. The template library stays. This cannot be undone.</p>
        </div>
        {armed && <button onClick={() => setArmed(false)} className="text-xs text-muted hover:text-fg">Cancel</button>}
        <Act perm="admin" variant="danger" icon={RotateCcw} loading={reset.isPending}
          onClick={() => (armed ? reset.mutate() : setArmed(true))}>{armed ? 'Click again to reset everything' : 'Reset workspace'}</Act>
      </div>
    </section>
  )
}
