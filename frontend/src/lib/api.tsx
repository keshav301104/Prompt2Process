import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

/* ================================================================== types (API_SPEC §2 + §4 + workspace) */
export type Step = {
  id: string; title: string; action: string; params: Record<string, unknown>; when: string | null
  on_error: { retry: number; fallback: string | null }; requires_approval: boolean; side_effect: boolean
}
export type Plan = { name: string; description: string; steps: Step[] }
export type Check = { id: string; name: string; passed: boolean; details: string[] }
export type CheckReport = { ok: boolean; checks: Check[]; errors: string[]; warnings: string[] }
export type KPIs = {
  tasks_total: number; tasks_done: number; tasks_waiting_approval: number; tasks_in_review: number; tasks_failed: number
  accuracy: number | null; hours_saved: number; money_saved_inr: number; ai_calls_total: number
  ai_calls_per_task: number; escalation_rate: number; avg_seconds_per_task: number
}
export type Promotion = { eligible: boolean; next_level: number | null; reason: string; accuracy: number | null; sample_size: number; threshold: number }
export type Employee = {
  id: string; name: string; role: string; role_key?: string; role_title?: string; template_id?: string | null
  sector: string; department: string; org: string; avatar_color: string; avatar_initials: string
  autonomy_level: 0 | 1 | 2; autonomy_label: string; limits: { auto_approve_below_inr: number }; tools: string[]
  plan: Plan; plan_version: number; sop_title: string; supervised_approvals?: number; created_at: string
  kpis: KPIs; promotion: Promotion; intake?: { type: string; path: string } | null
}
export type Flag = { type: string; severity: 'info' | 'warn' | 'critical'; message: string; evidence?: string; step_id?: string }
export type StepStatus = 'pending' | 'skipped' | 'running' | 'ok' | 'failed' | 'retrying' | 'waiting_approval' | 'simulated' | 'fallback'
export type StepRun = {
  step_id: string; title: string; action: string; status: StepStatus; started_at?: string; ended_at?: string
  attempts: number; output_preview?: string; error?: string; ai_calls: number
}
export type Field = { value: unknown; confidence: number; source: string }
export type TaskStatus = 'queued' | 'running' | 'waiting_approval' | 'needs_review' | 'done' | 'failed' | 'rejected'
export type Task = {
  id: string; employee_id: string; title: string; kind: 'invoice' | 'collection' | 'case'; status: TaskStatus
  mode: 'live' | 'shadow'; created_at: string; updated_at: string; plan_version?: number
  outcome: { route?: string; summary?: string; final_decision?: string }
  fields: Record<string, Field>; flags: Flag[]; steps: StepRun[]; ai_calls: number; duration_s: number | null
  source_file?: string; file?: string; files?: string[]; case_id?: string; folder?: string
}
export type InboxItem = {
  id: string; task_id: string | null; employee_id: string; kind: 'approval' | 'review' | 'healing'; title: string; reason: string
  payload: Record<string, any>; created_at: string; status: 'open' | 'done'
  decision?: { decision: 'approve' | 'reject'; note: string; by: string; at: string }
}
export type Event = { ts: string; level: 'info' | 'warn' | 'error' | 'success'; message: string; step_id?: string | null; task_id?: string }
export type Health = { status: string; llm_mode: string; model: string; vision_model: string; llm_error?: string | null; chaos_mode: boolean }
export type Settings = {
  chaos_mode: boolean; chaos_rate: number; hourly_cost_inr: number; minutes_per_invoice_manual: number
  minutes_per_collection_manual: number; minutes_per_case_manual?: number; extraction_mode: 'template_first' | 'llm_first'; llm_mode: string
}
export type Overview = {
  employees: number; tasks_done: number; hours_saved: number; money_saved_inr: number; ai_calls_total: number; open_inbox: number
  outcomes: Record<string, number>; flags_by_type: Record<string, number>
  ai_calls_series: { task_index: number; ai_calls: number; employee_id: string }[]; activity: Event[]
}
export type Person = { role: string; key?: string; name: string; email: string }
export type Org = {
  name: string; legal_name?: string; industry?: string; city?: string; state_code?: string; gstin?: string; currency?: string; people: Person[]
}
export type Workspace = { org: Org | null; setup_complete: boolean; employees: number; templates: number; demo_available: boolean }
/** A hireable template from the library (GET /api/packs). */
export type Template = {
  id: string; sector: string; department: string; case_noun: string; employee: { name: string; title: string; color?: string }
  documents: Record<string, string>; routes: Record<string, string>; hired_count: number; parameters?: Record<string, unknown>
  intake?: { type: string; path: string } | null; directory?: { key: string; role: string }[]
}
export type Role = { id: RoleId; label: string; about: string; can: string[] }
export type RoleId = 'owner' | 'manager' | 'designer' | 'reviewer' | 'auditor'
export type Draft = { draft_id: string; sop_summary: string; detected_role: string; method?: string; questions: { id: string; question: string; why: string; suggested: string }[] }
export type Compiled = { draft_id: string; plan: Plan; check: CheckReport; attempts: { attempt: number; ok: boolean; errors: string[]; by?: string }[]; tools: string[] }
export type Learning = {
  model_trained: boolean; labels: string[]; n_examples: number; n_corrections: number; cv_accuracy: number | null
  last_trained_at: string | null; ai_calls_saved: number; method: string
}
export type IssueStat = { type: string; tp: number; fp: number; fn: number; precision: number | null; recall: number | null }
export type BacktestRow = {
  file: string; vendor: string; total: number | null; expected_route: string; predicted_route: string; correct: boolean
  expected_issues: string[]; found_issues: string[]; ai_calls?: number
}
export type Backtest = {
  id: string; employee_id: string; status: 'running' | 'done' | 'error'; progress: number; n_tasks: number; route_accuracy: number | null
  per_issue: IssueStat[]; hours_saved: number; money_saved_inr: number; ai_calls: number; duration_s: number
  plan_version?: number; created_at?: string; rows?: BacktestRow[]
}
export type Version = { version: number; created_at: string; note: string }
export type Change = { step_id: string; kind: 'added' | 'removed' | 'changed'; field?: string; before?: unknown; after?: unknown }
export type AuditRow = { ts: string; actor: string; action: string; task_id?: string | null; detail: string }
export type Output = { id: string; kind: string; employee_id: string; task_id: string | null; data: Record<string, any> & { summary?: string }; created_at: string }
export type Trace = { mode: string; model: string; total_calls: number; calls: { ts: string; purpose: string; model: string; vision: boolean; prompt_chars: number; output_chars: number; seconds: number }[] }

/* ================================================================== client */
let role: RoleId = 'owner'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const isForm = body instanceof FormData
  const res = await fetch(`/api${path}`, {
    method,
    headers: { 'X-P2P-Role': role, ...(body !== undefined && !isForm ? { 'Content-Type': 'application/json' } : {}) },
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const j = await res.json()
      if (j?.detail) detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch { /* non-JSON error body */ }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

export const api = {
  get: <T,>(p: string) => request<T>('GET', p),
  post: <T,>(p: string, body: unknown = {}) => request<T>('POST', p, body),
  put: <T,>(p: string, body: unknown) => request<T>('PUT', p, body),
}

export function toastError(e: unknown) {
  if (e instanceof ApiError && e.status === 403) toast.error('Not permitted for this role', { description: e.message })
  else toast.error('Request failed', { description: e instanceof Error ? e.message : String(e) })
}

/* ================================================================== queries */
const LIVE = 2000
const q = <T,>(key: unknown[], path: string | null, refetchInterval: number | false = false) =>
  ({ queryKey: key, queryFn: () => api.get<T>(path!), enabled: path !== null, refetchInterval })

export const useHealth = () => useQuery(q<Health>(['health'], '/health', 5000))
export const useWorkspace = () => useQuery(q<Workspace>(['workspace'], '/workspace', 5000))
export const useOrg = () => useQuery(q<Org>(['org'], '/org'))
export const useRoles = () => useQuery(q<Role[]>(['roles'], '/roles'))
export const useTemplates = () => useQuery(q<Template[]>(['templates'], '/packs', 10000))
export const useOverview = () => useQuery(q<Overview>(['overview'], '/overview', LIVE))
export const useEmployees = () => useQuery(q<Employee[]>(['employees'], '/employees', LIVE))
export const useEmployee = (id?: string) => useQuery(q<Employee>(['employees', id], id ? `/employees/${id}` : null, LIVE))
export const useTasks = () => useQuery(q<Task[]>(['tasks'], '/tasks', LIVE))
export const useTask = (id?: string) => useQuery(q<Task>(['tasks', id], id ? `/tasks/${id}` : null, 1500))
export const useTaskEvents = (id?: string) => useQuery(q<Event[]>(['tasks', id, 'events'], id ? `/tasks/${id}/events` : null, 1500))
export const useSettings = () => useQuery(q<Settings>(['settings'], '/settings', 5000))
export const useAudit = () => useQuery(q<AuditRow[]>(['audit'], '/audit?limit=500', 4000))
export const useOutputs = () => useQuery(q<Output[]>(['outputs'], '/outputs?limit=500', 4000))
export const useTrace = () => useQuery(q<Trace>(['trace'], '/llm/trace', 4000))
export const useLearning = (id?: string) => useQuery(q<Learning>(['learning', id], id ? `/learning/${id}` : null))
export const useBacktests = (id?: string) => useQuery(q<Backtest[]>(['backtests', id], id ? `/employees/${id}/backtests` : null, LIVE))
export const useBacktest = (id?: string | null) => useQuery({
  ...q<Backtest>(['backtest', id], id ? `/backtests/${id}` : null),
  refetchInterval: (query: { state: { data?: Backtest } }) => (query.state.data?.status === 'running' ? 600 : false),
})
export const useVersions = (id?: string) => useQuery(q<Version[]>(['versions', id], id ? `/employees/${id}/versions` : null))
export const useDiff = (id: string, a: number | null, b: number | null) =>
  useQuery(q<{ changes: Change[] }>(['diff', id, a, b], a && b && a !== b ? `/employees/${id}/diff?a=${a}&b=${b}` : null))

/**
 * Open inbox items, minus approval items whose step has already moved on.
 * (When a run resumes after an approval the runner can re-issue an item for the step it just passed;
 * deciding such a stale item would resume the task at the *next* gate, so it is hidden.)
 */
export function useInbox() {
  const items = useQuery(q<InboxItem[]>(['inbox', 'open'], '/inbox?status=open', LIVE))
  const tasks = useTasks()
  const byId = new Map((tasks.data ?? []).map((t) => [t.id, t]))
  const live = (items.data ?? []).filter((i) => {
    if (i.kind !== 'approval' || !i.task_id) return true
    const step = byId.get(i.task_id)?.steps.find((s) => s.step_id === i.payload?.step_id)
    return !step || step.status === 'waiting_approval' || step.status === 'pending'
  })
  return { ...items, data: items.data ? live : undefined }
}
export const useDecided = () => useQuery(q<InboxItem[]>(['inbox', 'done'], '/inbox?status=done', 4000))

/** Mutation helper: toasts success / 403s and refreshes every query afterwards. */
export function useAction<A = void, R = unknown>(
  fn: (a: A) => Promise<R>,
  opts: { success?: string | ((r: R, a: A) => string); onDone?: (r: R, a: A) => void } = {},
) {
  const qc = useQueryClient()
  return useMutation<R, unknown, A>({
    mutationFn: fn,
    onSuccess: (r, a) => {
      const msg = typeof opts.success === 'function' ? opts.success(r, a) : opts.success
      if (msg) toast.success(msg)
      opts.onDone?.(r, a)
      void qc.invalidateQueries()
    },
    onError: toastError,
  })
}

/* ================================================================== session: "view as" role + theme */
/** Used until /api/roles answers (and if it never does). Mirrors the backend's permission table. */
const FALLBACK_ROLES: Role[] = [
  { id: 'owner', label: 'Owner', about: 'Sees every department; can do everything.', can: ['*'] },
  { id: 'manager', label: 'Department manager', about: 'Runs the team: work queues, approvals, promotions.',
    can: ['backtest.run', 'employee.promote', 'inbox.decide', 'learning.train', 'settings.edit', 'task.correct', 'work.run'] },
  { id: 'designer', label: 'Process designer', about: 'Hires from SOPs, edits workflows, runs backtests.',
    can: ['backtest.run', 'hire', 'learning.train', 'plan.check', 'plan.edit'] },
  { id: 'reviewer', label: 'Reviewer', about: 'Works the review inbox and corrects the AI.', can: ['inbox.decide', 'task.correct'] },
  { id: 'auditor', label: 'Auditor', about: 'Read-only: audit trail and evidence.', can: [] },
]
type Theme = 'dark' | 'light'
type Session = { role: Role; roles: Role[]; setRole: (r: RoleId) => void; can: (perm: string) => boolean; theme: Theme; toggleTheme: () => void }
const Ctx = createContext<Session | null>(null)
const read = (k: string) => { try { return localStorage.getItem(k) } catch { return null } }
const write = (k: string, v: string) => { try { localStorage.setItem(k, v) } catch { /* storage blocked */ } }

export function SessionProvider({ children }: { children: ReactNode }) {
  const rolesQ = useRoles()
  const roles = rolesQ.data?.length ? rolesQ.data : FALLBACK_ROLES
  const [roleId, setRoleId] = useState<RoleId>(() => {
    const r = read('p2p.role')
    role = FALLBACK_ROLES.some((x) => x.id === r) ? (r as RoleId) : 'owner'
    return role
  })
  const [theme, setTheme] = useState<Theme>(() => (read('p2p.theme') === 'light' ? 'light' : 'dark'))
  useEffect(() => { document.documentElement.dataset.theme = theme; write('p2p.theme', theme) }, [theme])
  const setRole = useCallback((r: RoleId) => { role = r; write('p2p.role', r); setRoleId(r) }, [])
  const value = useMemo<Session>(() => {
    const current = roles.find((r) => r.id === roleId) ?? roles[0]
    return {
      role: current, roles, setRole, theme, toggleTheme: () => setTheme((t) => (t === 'dark' ? 'light' : 'dark')),
      can: (perm) => current.can.includes('*') || current.can.includes(perm),
    }
  }, [roles, roleId, setRole, theme])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useSession() {
  const s = useContext(Ctx)
  if (!s) throw new Error('useSession outside SessionProvider')
  return s
}
