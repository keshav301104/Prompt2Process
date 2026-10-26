import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import type { Employee, TaskStatus, Template } from './api'

export const cn = (...v: ClassValue[]) => twMerge(clsx(v))

/* ------------------------------------------------------------------ numbers (en-IN) */
const nf = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 1 })
export const num = (n: number | null | undefined, digits = 0) => (n == null ? '—' : (digits ? nf1 : nf).format(n))
export const inr = (n: number | null | undefined) => (n == null ? '—' : `₹${nf.format(n)}`)
/** ₹ in lakh / crore for headline numbers. */
export const inrShort = (n: number | null | undefined) => {
  if (n == null) return '—'
  if (Math.abs(n) >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`
  if (Math.abs(n) >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`
  return inr(n)
}
export const pct = (x: number | null | undefined, digits = 0) => (x == null ? '—' : `${(x * 100).toFixed(digits)}%`)

/* ------------------------------------------------------------------ time */
export const ago = (iso?: string | null) => {
  if (!iso) return '—'
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 45) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return `${Math.round(s / 86400)}d ago`
}
export const stamp = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : '—'
export const clock = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : '—'

/* ------------------------------------------------------------------ words */
export const humanize = (s?: string | null) => {
  if (!s) return '—'
  const t = s.replace(/[_-]+/g, ' ').trim()
  return t.charAt(0).toUpperCase() + t.slice(1)
}
const ACRONYMS: Record<string, string> = { gstin: 'GSTIN', po: 'PO', no: 'No.', id: 'ID', pan: 'PAN', ifsc: 'IFSC', emi: 'EMI', dti: 'DTI', foir: 'FOIR', cgpa: 'CGPA', hsn: 'HSN', ai: 'AI' }
/** Field keys arrive as snake_case ("vendor_gstin") or human labels ("Loan Amount"). */
export const fieldLabel = (k: string) =>
  /[A-Z ]/.test(k) ? k : humanize(k).split(' ').map((w) => ACRONYMS[w.toLowerCase()] ?? w).join(' ')
/** Heuristic: is this field a rupee amount? */
export const isMoneyField = (k: string) =>
  /total|amount|value|bill|payable|insured|claimed|charges|medicines|consumables|rent|income|salary|limit|loan|refund|price|cover|cap|excess|deduct/i.test(k) || /(^|[\s_])(emi|fee|fees)($|[\s_])/i.test(k)
export const shortId = (id: string) => id.replace(/^(tsk|inb|emp|bt|draft)_/, '')

/* ------------------------------------------------------------------ sectors
 * Nothing is hard-coded: sectors come from the template library and from hired employees.
 * Each new sector takes the next slot of a fixed, colour-vision-validated palette (--s-1 … --s-7). */
const sectorOrder: string[] = []
export const registerSectors = (names: (string | undefined)[]) => {
  for (const n of names) if (n && !sectorOrder.includes(n)) sectorOrder.push(n)
}
export const sectorRank = (name?: string) => {
  const i = name ? sectorOrder.indexOf(name) : -1
  return i < 0 ? 99 : i
}
export const sectorMeta = (name?: string) => {
  const i = sectorRank(name)
  return { name: name ?? 'Other', short: (name ?? 'Other').split(' & ')[0], color: i === 99 ? 'var(--fg-subtle)' : `var(--s-${(i % 7) + 1})` }
}
export const sortEmployees = (list: Employee[]) =>
  [...list].sort((a, b) => sectorRank(a.sector) - sectorRank(b.sector) || a.created_at.localeCompare(b.created_at))

/* ------------------------------------------------------------------ statuses, routes, autonomy */
export type Tone = 'neutral' | 'accent' | 'ok' | 'warn' | 'bad'
export const TASK_STATUS: Record<TaskStatus, { label: string; tone: Tone }> = {
  queued: { label: 'Queued', tone: 'neutral' },
  running: { label: 'Running', tone: 'accent' },
  waiting_approval: { label: 'Awaiting approval', tone: 'accent' },
  needs_review: { label: 'Needs review', tone: 'warn' },
  done: { label: 'Done', tone: 'ok' },
  failed: { label: 'Failed', tone: 'bad' },
  rejected: { label: 'Rejected', tone: 'bad' },
}

/** Route ids are labelled by the template library; anything else is humanised. */
export function routeLabel(route: string | undefined | null, templates?: Template[]) {
  if (!route) return '—'
  for (const t of templates ?? []) if (t.routes?.[route]) return t.routes[route]
  return humanize(route)
}
/** Tone for a route / final decision id. */
export function routeTone(route?: string | null): Tone {
  if (!route) return 'neutral'
  if (/reject|declin|repudiat|failed/.test(route)) return 'bad'
  if (/review|query|request|approval|escalat/.test(route)) return 'warn'
  return 'ok'
}

export const AUTONOMY = [
  { label: 'Shadow', blurb: 'Runs on real work but only simulates side effects. Scored by backtests.' },
  { label: 'Supervised', blurb: 'Acts for real; a manager signs off each case’s actions before they happen.' },
  { label: 'Autonomous', blurb: 'Acts on its own within SOP limits; humans only see exceptions.' },
]

export const MONEY_ACTIONS = new Set(['issue_refund', 'add_to_payment_batch', 'post_journal_entry'])

export const PERMS: Record<string, string> = {
  'work.run': 'run and ingest work',
  'inbox.decide': 'decide inbox items',
  'employee.promote': 'change autonomy',
  'settings.edit': 'change settings',
  'learning.train': 'train models',
  'task.correct': 'correct extracted fields',
  'backtest.run': 'run backtests',
  hire: 'hire employees',
  'plan.edit': 'save workflow versions',
  'plan.check': 'check workflows',
  admin: 'reset or load the demo workspace',
}
