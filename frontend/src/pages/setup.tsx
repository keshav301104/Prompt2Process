import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, Building2, CheckCircle2, FlaskConical, Plus, Sparkles, Trash2, Users, XCircle } from 'lucide-react'
import { api, useAction, useOrg, useTemplates, useWorkspace, type Org, type Person, type Workspace } from '../lib/api'
import { cn } from '../lib/format'
import { Act, Input, Label, Load, LogoMark, Panel, PanelHead, Pill, Select, Skeleton } from '../components/ui'

/* ------------------------------------------------------------------ GSTIN (format + mod-36 check digit) */
const CH = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
function gstinStatus(g: string): 'empty' | 'valid' | 'format' | 'checksum' {
  const v = g.trim().toUpperCase()
  if (!v) return 'empty'
  if (!/^[0-3][0-9][A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/.test(v)) return 'format'
  let t = 0
  for (let i = 0; i < 14; i++) { const p = CH.indexOf(v[i]) * (i % 2 ? 2 : 1); t += Math.floor(p / 36) + (p % 36) }
  return CH[(36 - (t % 36)) % 36] === v[14] ? 'valid' : 'checksum'
}
const slug = (s: string) => s.toLowerCase().trim().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '')
const blankPerson = (): Person => ({ role: '', name: '', email: '' })

/** Company profile + people & approvers. Used by first-run setup and by Settings. */
export function OrgForm({ initial, submitLabel, onSaved, autoFocus }: { initial?: Org | null; submitLabel: string; onSaved?: (o: Org) => void; autoFocus?: boolean }) {
  const templates = useTemplates()
  const [org, setOrg] = useState<Org>(() => ({
    name: '', legal_name: '', industry: '', city: '', state_code: '', gstin: '', currency: 'INR', ...initial,
    people: initial?.people?.length ? initial.people : [blankPerson()],
  }))
  const set = (k: keyof Org, v: string) => setOrg((o) => ({ ...o, [k]: v }))
  const setPerson = (i: number, k: keyof Person, v: string) => setOrg((o) => ({ ...o, people: o.people.map((p, j) => (j === i ? { ...p, [k]: v } : p)) }))
  const gst = gstinStatus(org.gstin ?? '')
  const people = org.people.filter((p) => p.role.trim() && p.name.trim())
  const save = useAction(() => api.put<Org>('/org', {
    ...org, gstin: org.gstin?.trim().toUpperCase() || '', state_code: org.state_code || (gst === 'valid' ? org.gstin!.slice(0, 2) : ''),
    people: people.map((p) => ({ ...p, key: p.key || slug(p.role) })),
  }), { success: 'Workspace profile saved', onDone: (o) => onSaved?.(o) })
  const sectors = [...new Set((templates.data ?? []).map((t) => t.sector))]
  // Roles the template library routes approvals to — offered as one-click rows, never pre-filled.
  const have = new Set(org.people.map((p) => p.key || slug(p.role)))
  const suggested = [...new Map((templates.data ?? []).flatMap((t) => t.directory ?? []).map((d) => [d.key, d])).values()].filter((d) => !have.has(d.key))
  const addRole = (d: { key: string; role: string }) =>
    setOrg((o) => ({ ...o, people: [...o.people.filter((p) => p.role.trim() || p.name.trim()), { key: d.key, role: d.role, name: '', email: '' }] }))

  return (
    <div className="space-y-5">
      <Panel>
        <PanelHead title={<span className="flex items-center gap-2"><Building2 className="size-4 text-subtle" />Company profile</span>} hint="Shown on documents, used for GST checks and every SOP that mentions “the company”" />
        <div className="grid grid-cols-1 gap-4 p-4 md:grid-cols-2">
          <div><Label>Company name</Label><Input value={org.name} onChange={(e) => set('name', e.target.value)} placeholder="Trading name" autoFocus={autoFocus} /></div>
          <div><Label hint="optional">Legal name</Label><Input value={org.legal_name ?? ''} onChange={(e) => set('legal_name', e.target.value)} placeholder="As registered, e.g. … Pvt Ltd" /></div>
          <div><Label>Industry</Label>
            <Input list="p2p-industries" value={org.industry ?? ''} onChange={(e) => set('industry', e.target.value)} placeholder="e.g. Food processing" />
            <datalist id="p2p-industries">{sectors.map((s) => <option key={s} value={s} />)}</datalist></div>
          <div><Label>City</Label><Input value={org.city ?? ''} onChange={(e) => set('city', e.target.value)} placeholder="e.g. Vijayawada" /></div>
          <div><Label hint="2 digits, from GSTIN if left blank">State code</Label>
            <Input value={org.state_code ?? ''} maxLength={2} onChange={(e) => set('state_code', e.target.value.replace(/\D/g, ''))} placeholder={gst === 'valid' ? org.gstin!.slice(0, 2) : 'e.g. 37'} /></div>
          <div><Label hint={gst === 'empty' ? 'optional' : gst === 'valid' ? <span className="flex items-center gap-1 text-ok"><CheckCircle2 className="size-3" />valid</span>
              : <span className="flex items-center gap-1 text-bad"><XCircle className="size-3" />{gst === 'format' ? 'invalid format' : 'check digit mismatch'}</span>}>GSTIN</Label>
            <Input className="font-mono uppercase" value={org.gstin ?? ''} maxLength={15} onChange={(e) => set('gstin', e.target.value)} placeholder="15-character GSTIN" /></div>
          <div><Label>Currency</Label><Select value={org.currency ?? 'INR'} disabled><option value="INR">INR — Indian rupee (₹)</option></Select></div>
        </div>
      </Panel>
      <Panel>
        <PanelHead title={<span className="flex items-center gap-2"><Users className="size-4 text-subtle" />People & approvers</span>}
          hint="When an SOP says “ask the Finance Manager”, employees resolve it to the person named here" />
        <div className="p-4">
          <div className="grid grid-cols-[1fr_1fr_1.2fr_32px] gap-2 pb-1.5 text-xs font-medium text-muted"><span>Role</span><span>Name</span><span>Email</span><span /></div>
          <div className="space-y-2">
            {org.people.map((p, i) => (
              <div key={i} className="grid grid-cols-[1fr_1fr_1.2fr_32px] items-center gap-2">
                <Input value={p.role} onChange={(e) => setPerson(i, 'role', e.target.value)} placeholder="e.g. Finance Manager" />
                <Input value={p.name} onChange={(e) => setPerson(i, 'name', e.target.value)} placeholder="Full name" />
                <Input type="email" value={p.email} onChange={(e) => setPerson(i, 'email', e.target.value)} placeholder="name@company.in" />
                <button aria-label="Remove person" onClick={() => setOrg((o) => ({ ...o, people: o.people.length > 1 ? o.people.filter((_, j) => j !== i) : [blankPerson()] }))}
                  className="flex size-8 items-center justify-center rounded-md text-subtle hover:bg-raised hover:text-bad"><Trash2 className="size-3.5" /></button>
              </div>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <button onClick={() => setOrg((o) => ({ ...o, people: [...o.people, blankPerson()] }))}
              className="mr-2 inline-flex items-center gap-1.5 text-sm font-medium text-accent hover:underline"><Plus className="size-3.5" />Add person</button>
            {suggested.length > 0 && <span className="text-xs text-subtle">Templates route approvals to:</span>}
            {suggested.map((d) => (
              <button key={d.key} onClick={() => addRole(d)} className="inline-flex h-6 items-center gap-1 rounded-full border border-dashed border-line-strong px-2 text-xs text-muted hover:border-accent hover:text-fg">
                <Plus className="size-3" />{d.role}</button>
            ))}
          </div>
        </div>
      </Panel>
      <div className="flex items-center justify-end gap-3">
        {!org.name.trim() && <span className="text-xs text-subtle">A company name is required</span>}
        <Act perm="settings.edit" variant="primary" icon={ArrowRight} disabled={!org.name.trim() || gst === 'format' || gst === 'checksum'}
          loading={save.isPending} onClick={() => save.mutate()}>{submitLabel}</Act>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ first-run screen */
export function SetupPage() {
  const ws = useWorkspace()
  const org = useOrg()
  const nav = useNavigate()
  const demo = useAction(() => api.post<Workspace>('/workspace/demo'), { success: 'Demo workspace ready — meet your team', onDone: () => nav('/') })
  const steps = ['Company profile', 'People & approvers', 'Hire your first digital employee']
  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <div className="flex items-center gap-3">
        <LogoMark className="size-9" />
        <div>
          <div className="text-xs font-medium tracking-wider text-accent uppercase">Welcome to Prompt2Process</div>
          <h1 className="text-2xl font-semibold tracking-tight">Set up your workspace</h1>
        </div>
      </div>
      <p className="mt-3 max-w-2xl text-base text-muted">Turn any SOP into a digital employee. Start by telling us who you are — nothing is pre-filled, and every employee you hire reads its company details and approvers from here.</p>
      <ol className="mt-6 flex flex-wrap items-center gap-2 text-sm">
        {steps.map((s, i) => (
          <li key={s} className="flex items-center gap-2">
            {i > 0 && <span className="h-px w-8 bg-line-strong" />}
            <span className={cn('flex size-5 items-center justify-center rounded-full text-2xs font-semibold', i < 2 ? 'border border-accent text-accent' : 'border border-line-strong text-subtle')}>{i + 1}</span>
            <span className={i < 2 ? 'text-fg' : 'text-subtle'}>{s}</span>
          </li>
        ))}
      </ol>
      <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
        <Load q={org} skeleton={<Skeleton className="h-96" />}>{(o) => <OrgForm initial={o} autoFocus submitLabel="Save & hire your first employee" onSaved={() => nav('/hire')} />}</Load>
        <aside className="space-y-4">
          <Panel className="p-4">
            <div className="flex items-center gap-2 text-sm font-semibold"><FlaskConical className="size-4 text-accent" />Just exploring?</div>
            <p className="mt-1.5 text-sm text-muted">Load a demo organisation and hire a sample team across sectors through the normal pipeline — clarify, compile, check — in a few seconds.</p>
            {ws.data && <p className="mt-2 text-xs text-subtle">{ws.data.templates} templates in the library</p>}
            <Act perm="admin" className="mt-3" block icon={Sparkles} loading={demo.isPending} disabled={ws.data?.demo_available === false}
              onClick={() => demo.mutate()}>{demo.isPending ? 'Hiring the demo team…' : 'Load demo workspace'}</Act>
          </Panel>
          <Panel className="p-4">
            <div className="text-sm font-semibold">What happens next</div>
            <ol className="mt-2 space-y-2 text-sm text-muted">
              {['Pick a template or upload your own SOP', 'Answer the questions the SOP leaves open', 'The compiler checks the workflow (8 checks)', 'Your employee starts in Shadow and earns autonomy'].map((s, i) => (
                <li key={s} className="flex gap-2"><span className="mt-px flex size-4 shrink-0 items-center justify-center rounded-full bg-raised text-2xs text-subtle">{i + 1}</span>{s}</li>
              ))}
            </ol>
            <div className="mt-3"><Pill>Starts empty · no seeded data</Pill></div>
          </Panel>
        </aside>
      </div>
    </div>
  )
}
