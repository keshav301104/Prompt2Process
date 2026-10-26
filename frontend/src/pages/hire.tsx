import { Fragment, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Check, CheckCircle2, Cpu, FileText, FileUp, HelpCircle, Pencil, Sparkles, Upload, UserPlus, Wrench, XCircle } from 'lucide-react'
import { api, useAction, useOrg, useTemplates, type Compiled, type Draft, type Employee, type Template } from '../lib/api'
import { cn, humanize, num, sectorMeta, sectorRank } from '../lib/format'
import { CheckReportView, PlanGraph } from '../components/plan-graph'
import { Act, Button, Empty, Input, Label, Load, Mono, PageHeader, Panel, PanelHead, Pill, SectorDot, Skeleton, Textarea } from '../components/ui'

const STEPS = ['Choose a template', 'Clarify', 'Compile & hire']
const CUSTOM = '__custom__'

export function HirePage() {
  const templates = useTemplates()
  return (
    <Load q={templates} skeleton={<div className="space-y-3 p-6"><Skeleton className="h-10 w-96" /><Skeleton className="h-[60vh]" /></div>}>
      {(list) => <Wizard templates={list} />}
    </Load>
  )
}

function Wizard({ templates }: { templates: Template[] }) {
  const [sp] = useSearchParams()
  const nav = useNavigate()
  const pre = templates.find((t) => t.id === sp.get('template'))
  const [stage, setStage] = useState(0)
  const [pick, setPick] = useState<string | null>(pre?.id ?? null)
  const [name, setName] = useState(pre?.employee.name ?? '')
  const [text, setText] = useState('')
  const [editSop, setEditSop] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [compiled, setCompiled] = useState<Compiled | null>(null)
  const tpl = templates.find((t) => t.id === pick)
  const custom = pick === CUSTOM

  const choose = (id: string) => { setPick(id); setEditSop(false); setFile(null); setName(templates.find((t) => t.id === id)?.employee.name ?? '') }
  const makeDraft = useAction(async () => {
    if (custom && file && /\.pdf$/i.test(file.name)) {
      const fd = new FormData()
      fd.append('file', file); fd.append('name', name)
      return api.post<Draft>('/hire/draft-upload', fd)
    }
    const sop = custom && file ? await file.text() : text
    return api.post<Draft>('/hire/draft', { name: name.trim(), template_id: custom ? undefined : pick, sop_text: custom ? sop : editSop && text ? text : undefined })
  }, { onDone: (d) => { setDraft(d); setAnswers(Object.fromEntries(d.questions.map((q) => [q.id, q.suggested]))); setStage(1) } })
  const compile = useAction(() => api.post<Compiled>('/hire/compile', { draft_id: draft!.draft_id, answers }), { onDone: (c) => { setCompiled(c); setStage(2) } })
  const confirm = useAction(() => api.post<Employee>('/hire/confirm', { draft_id: draft!.draft_id }), {
    success: (e) => `${e.name} hired — starts in Shadow mode`, onDone: (e) => nav(`/employees/${e.id}`),
  })
  const ready = name.trim().length > 0 && (custom ? !!file || text.trim().length >= 40 : !!tpl)

  return (
    <div>
      <PageHeader title="Hire a digital employee" subtitle="Start from a template or your own SOP. Gemma 4 asks about the gaps, compiles a typed workflow, and the checker proves it safe before anyone is hired.">
        <ol className="flex items-center gap-2 pb-3.5">
          {STEPS.map((s, i) => (
            <Fragment key={s}>
              {i > 0 && <span className={cn('h-px w-10', i <= stage ? 'bg-accent' : 'bg-line-strong')} />}
              <li className={cn('flex items-center gap-2 text-sm', i === stage ? 'font-medium text-fg' : i < stage ? 'text-muted' : 'text-subtle')}>
                <span className={cn('flex size-5 items-center justify-center rounded-full text-2xs font-semibold', i < stage ? 'bg-accent-strong text-accent-fg' : i === stage ? 'border border-accent text-accent' : 'border border-line-strong')}>
                  {i < stage ? <Check className="size-3" /> : i + 1}</span>{s}
              </li>
            </Fragment>
          ))}
        </ol>
      </PageHeader>
      <div className="p-6">
        {stage === 0 && (
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_400px]">
            <TemplateGrid templates={templates} picked={pick} onPick={choose} />
            <Panel className="h-fit xl:sticky xl:top-6">
              <PanelHead title={custom ? 'Your own SOP' : tpl ? tpl.employee.title : 'Configure the hire'} hint={custom ? 'Paste or upload any procedure document' : tpl ? `${tpl.sector} · ${tpl.department}` : 'Pick a template on the left'} />
              <div className="space-y-4 p-4">
                {!pick && <Empty icon={UserPlus} title="Choose what to hire" body="Templates are complete SOPs you can edit. Or bring your own SOP — any department, any sector." className="py-6" />}
                {tpl && <TemplateFacts t={tpl} />}
                {pick && (
                  <div><Label hint={tpl?.employee.name ? 'suggested — change it if you like' : undefined}>Employee name</Label>
                    <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Give your digital employee a name" /></div>
                )}
                {tpl && <SopEditor templateId={tpl.id} open={editSop} setOpen={setEditSop} text={text} setText={setText} />}
                {custom && (
                  <>
                    {file ? (
                      <div className="flex items-center gap-3 rounded-md border border-line-strong bg-sunken px-3 py-3 text-sm">
                        <FileText className="size-4 text-accent" /><span className="flex-1 truncate">{file.name}</span>
                        <Button size="sm" variant="ghost" onClick={() => setFile(null)}>Remove</Button>
                      </div>
                    ) : <div><Label hint={`${num(text.length)} characters`}>Standard operating procedure</Label>
                      <Textarea rows={12} value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste the SOP here — numbered steps, limits, approvers…" className="text-xs leading-5" /></div>}
                    <div className="flex items-center gap-2">
                      <label className="inline-flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-md border border-line-strong px-3 text-sm hover:bg-raised">
                        <Upload className="size-3.5" />Upload .md, .txt or .pdf
                        <input type="file" accept=".md,.txt,.pdf" className="hidden" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
                      </label>
                      {!file && <SamplePicker onPick={setText} />}
                    </div>
                  </>
                )}
                {pick && <Act perm="hire" variant="primary" block icon={Sparkles} disabled={!ready} loading={makeDraft.isPending} onClick={() => makeDraft.mutate()}>Read SOP & ask questions</Act>}
              </div>
            </Panel>
          </div>
        )}

        {stage === 1 && draft && (
          <div className="max-w-4xl space-y-5">
            <Panel className="p-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold">{name}</span>
                {tpl && <Pill tone="accent">{tpl.employee.title}</Pill>}
                {draft.method && <Pill icon={Cpu}>{draft.method === 'offline' ? 'offline fallback' : draft.method}</Pill>}
              </div>
              <p className="mt-2 text-sm text-muted">{draft.sop_summary.replace(/\*\*/g, '')}</p>
            </Panel>
            <div>
              <h2 className="mb-1 text-base font-semibold">{draft.questions.length} clarifying question{draft.questions.length === 1 ? '' : 's'}</h2>
              <p className="mb-3 text-sm text-muted">The SOP leaves these open. Suggested answers are pre-filled — edit anything that doesn’t match how you work.</p>
              <div className="space-y-3">
                {draft.questions.length === 0 && <Panel><Empty icon={CheckCircle2} title="No open questions" body="The SOP is specific enough to compile as-is." className="py-8" /></Panel>}
                {draft.questions.map((q, i) => (
                  <Panel key={q.id} className="p-4">
                    <div className="flex gap-3">
                      <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-accent/15 text-xs font-semibold text-accent">{i + 1}</span>
                      <div className="min-w-0 flex-1 space-y-2">
                        <p className="text-sm font-medium">{q.question}</p>
                        <p className="flex items-center gap-1.5 text-xs text-subtle"><HelpCircle className="size-3.5" />{q.why}</p>
                        <Textarea rows={2} value={answers[q.id] ?? ''} onChange={(e) => setAnswers((a) => ({ ...a, [q.id]: e.target.value }))} />
                      </div>
                    </div>
                  </Panel>
                ))}
              </div>
            </div>
            <div className="flex justify-between">
              <Button icon={ArrowLeft} onClick={() => setStage(0)}>Back</Button>
              <Act perm="hire" variant="primary" icon={Wrench} loading={compile.isPending} onClick={() => compile.mutate()}>Compile workflow</Act>
            </div>
          </div>
        )}

        {stage === 2 && compiled && (
          <div className="space-y-5">
            <div className="grid grid-cols-1 gap-5 xl:grid-cols-5">
              <div className="space-y-5 xl:col-span-2">
                <CompilerLog c={compiled} />
                <Panel className="p-4"><CheckReportView report={compiled.check} compact /></Panel>
                <Panel className="p-4">
                  <Label hint={`${compiled.tools.length} tools`}>Least-privilege tool grant</Label>
                  <div className="flex flex-wrap gap-1">{compiled.tools.map((t) => <span key={t} className="rounded border border-line bg-sunken px-1.5 py-0.5 font-mono text-2xs text-muted">{t}</span>)}</div>
                </Panel>
              </div>
              <Panel className="flex flex-col overflow-hidden xl:col-span-3">
                <PanelHead title={compiled.plan.name} hint={`${compiled.plan.steps.length} steps · read-only preview`} />
                <div className="h-[620px]"><PlanGraph plan={compiled.plan} /></div>
              </Panel>
            </div>
            <div className="flex justify-between">
              <Button icon={ArrowLeft} onClick={() => setStage(1)}>Back to questions</Button>
              <Act perm="hire" variant="primary" icon={UserPlus} disabled={!compiled.check.ok} loading={confirm.isPending} onClick={() => confirm.mutate()}>Hire {name} · starts in Shadow</Act>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function TemplateGrid({ templates, picked, onPick }: { templates: Template[]; picked: string | null; onPick: (id: string) => void }) {
  const groups = useMemo(() => {
    const m = new Map<string, Template[]>()
    for (const t of [...templates].sort((a, b) => sectorRank(a.sector) - sectorRank(b.sector))) m.set(t.sector, [...(m.get(t.sector) ?? []), t])
    return [...m.entries()]
  }, [templates])
  const card = 'relative flex w-full flex-col rounded-lg border bg-panel p-4 text-left transition-colors hover:border-line-strong'
  return (
    <div className="space-y-5">
      <button onClick={() => onPick(CUSTOM)} className={cn(card, 'w-full flex-row items-center gap-4 border-dashed', picked === CUSTOM ? 'border-accent ring-2 ring-accent/20' : 'border-line-strong')}>
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-line bg-raised"><FileUp className="size-4 text-accent" /></span>
        <span className="flex-1"><span className="block font-medium">Upload your own SOP</span>
          <span className="block text-sm text-muted">Any department, any sector — paste text or upload a .md, .txt or .pdf. The compiler maps it onto the tool library.</span></span>
      </button>
      <div className="gap-4 md:columns-2">{groups.map(([sector, list]) => (
        <section key={sector} className="mb-4 break-inside-avoid">
          <div className="mb-2 flex items-center gap-2 text-xs font-medium tracking-wider text-subtle uppercase"><SectorDot sector={sector} />{sector}</div>
          <div className="space-y-3">
            {list.map((t) => (
              <button key={t.id} onClick={() => onPick(t.id)} className={cn(card, picked === t.id ? 'border-accent ring-2 ring-accent/20' : 'border-line')}>
                <span className="absolute inset-x-0 top-0 h-[2px] rounded-t-lg opacity-80" style={{ background: sectorMeta(t.sector).color }} />
                <span className="flex items-start gap-2">
                  <span className="flex-1"><span className="block font-medium">{t.employee.title}</span><span className="block text-xs text-muted">{t.department} · {t.case_noun}s</span></span>
                  {t.hired_count > 0 && <Pill tone="ok" icon={Check}>{t.hired_count} hired</Pill>}
                </span>
                <span className="mt-3 flex flex-wrap gap-1">{Object.values(t.documents ?? {}).slice(0, 3).map((d) => <span key={d} className="rounded border border-line bg-sunken px-1.5 py-0.5 text-2xs text-muted">{d}</span>)}</span>
                <span className="mt-3 text-xs text-subtle">{Object.keys(t.routes ?? {}).length > 0 && `${Object.keys(t.routes).length} outcomes · `}suggested name <b className="font-medium text-muted">{t.employee.name}</b></span>
              </button>
            ))}
          </div>
        </section>
      ))}</div>
    </div>
  )
}

const paramValue = (v: unknown) =>
  typeof v === 'number' ? num(v) : typeof v === 'string' ? v : Array.isArray(v) ? `${v.length} items` : v && typeof v === 'object' ? `${Object.keys(v).length} entries` : String(v)

function TemplateFacts({ t }: { t: Template }) {
  const org = useOrg()
  const params = Object.entries(t.parameters ?? {}).filter(([, v]) => typeof v === 'number' || typeof v === 'string')
  const known = new Set((org.data?.people ?? []).filter((p) => p.name).map((p) => p.key))
  return (
    <div className="space-y-3 text-sm">
      {t.intake && <div className="flex items-center gap-2 text-xs text-subtle">Intake channel <Pill>{t.intake.type}</Pill><Mono>{t.intake.path}</Mono></div>}
      {Object.keys(t.documents ?? {}).length > 0 && <div><div className="mb-1 text-xs text-subtle">Reads per {t.case_noun}</div>
        <ul className="space-y-0.5">{Object.values(t.documents).map((d) => <li key={d} className="flex items-center gap-1.5 text-muted"><FileText className="size-3.5 text-subtle" />{d}</li>)}</ul></div>}
      {Object.keys(t.routes ?? {}).length > 0 && <div><div className="mb-1 text-xs text-subtle">Outcomes</div>
        <div className="flex flex-wrap gap-1">{Object.values(t.routes).map((r) => <Pill key={r}>{r}</Pill>)}</div></div>}
      {params.length > 0 && (
        <div><div className="mb-1 text-xs text-subtle">SOP parameters</div>
          <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-0.5 text-xs">{params.slice(0, 6).map(([k, v]) => (
            <Fragment key={k}><dt className="truncate text-muted">{humanize(k)}</dt><dd className="text-right font-mono">{paramValue(v)}</dd></Fragment>))}</dl></div>
      )}
      {!!t.directory?.length && (
        <div><div className="mb-1 text-xs text-subtle">Approvers it routes to</div>
          <ul className="space-y-0.5">{t.directory.map((d) => (
            <li key={d.key} className="flex items-center gap-1.5 text-xs">{known.has(d.key) ? <CheckCircle2 className="size-3.5 text-ok" /> : <XCircle className="size-3.5 text-warn" />}
              <span className="text-muted">{d.role}</span>{!known.has(d.key) && <span className="text-subtle">— not in your directory yet (you’ll be asked)</span>}</li>))}</ul></div>
      )}
    </div>
  )
}

/** "Upload your own SOP" helper: sample SOP documents shipped with the workspace (not templates). */
function SamplePicker({ onPick }: { onPick: (text: string) => void }) {
  const sops = useQuery({ queryKey: ['sops'], queryFn: () => api.get<{ id: string; title: string; text: string; template_id: string | null }[]>('/sops'), retry: false })
  const samples = (sops.data ?? []).filter((s) => !s.template_id)
  if (!samples.length) return null
  return (
    <select aria-label="Load a sample SOP" value="" onChange={(e) => onPick(samples.find((s) => s.id === e.target.value)?.text ?? '')}
      className="h-8 min-w-0 flex-1 rounded-md border border-line-strong bg-sunken pr-7 pl-2.5 text-sm text-muted">
      <option value="">Use a sample SOP…</option>
      {samples.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
    </select>
  )
}

/** Optional: edit the template's SOP text before compiling (sent as sop_text alongside template_id). */
function SopEditor({ templateId, open, setOpen, text, setText }: { templateId: string; open: boolean; setOpen: (v: boolean) => void; text: string; setText: (v: string) => void }) {
  const sops = useQuery({ queryKey: ['sops'], queryFn: () => api.get<{ id: string; text: string }[]>('/sops'), enabled: open, retry: false })
  const sop = sops.data?.find((s) => s.id === templateId)
  if (!open) return <button onClick={() => setOpen(true)} className="flex items-center gap-1.5 text-sm text-accent hover:underline"><Pencil className="size-3.5" />Review & edit the SOP first</button>
  if (sops.isLoading) return <Skeleton className="h-40" />
  if (!sop) return <p className="flex items-center gap-1.5 text-xs text-subtle"><XCircle className="size-3.5" />This template’s SOP text isn’t available to edit — it will be used as-is.</p>
  return <div><Label hint={<button onClick={() => { setOpen(false); setText('') }} className="hover:text-fg">use original</button>}>Template SOP (edited copy)</Label>
    <Textarea rows={12} value={text || sop.text} onChange={(e) => setText(e.target.value)} className="text-xs leading-5" /></div>
}

function CompilerLog({ c }: { c: Compiled }) {
  const [shown, setShown] = useState(0)
  useEffect(() => {
    if (shown >= c.attempts.length + 1) return
    const t = setTimeout(() => setShown((n) => n + 1), 550)
    return () => clearTimeout(t)
  }, [shown, c.attempts.length])
  return (
    <Panel>
      <PanelHead title="Compiler" hint="Plan → checker → repair loop (max 2 rounds)" />
      <ol className="space-y-3 p-4">
        {c.attempts.slice(0, shown).map((a) => (
          <li key={a.attempt} className="flex animate-in gap-3">
            {a.ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-ok" /> : <XCircle className="mt-0.5 size-4 shrink-0 text-bad" />}
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium">Attempt {a.attempt} <span className="font-normal text-subtle">· {a.by ?? 'gemma'}</span></div>
              {a.ok ? <p className="text-xs text-ok">Valid plan</p> : (
                <>{a.errors.map((e) => <Mono key={e} className="block text-2xs leading-4 text-bad">{e}</Mono>)}<p className="mt-1 text-xs text-muted">↳ errors fed back for repair</p></>
              )}
            </div>
          </li>
        ))}
        {shown > c.attempts.length && (
          <li className="flex animate-in items-center gap-2 rounded-md border border-ok/30 bg-ok/5 px-3 py-2 text-sm">
            <Sparkles className="size-4 text-ok" /><span><b>{c.plan.steps.length}-step workflow</b> compiled and {c.check.ok ? 'passes every check' : 'still has errors'}.</span>
          </li>
        )}
      </ol>
    </Panel>
  )
}
