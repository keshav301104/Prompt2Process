import { Component, type ButtonHTMLAttributes, type ErrorInfo, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react'
import type { UseQueryResult } from '@tanstack/react-query'
import { AlertTriangle, Eye, Loader2, ShieldCheck, Zap, type LucideIcon } from 'lucide-react'
import { ApiError, useSession, type Employee, type TaskStatus } from '../lib/api'
import { cn, PERMS, sectorMeta, TASK_STATUS, type Tone } from '../lib/format'

/* ------------------------------------------------------------------ buttons */
type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'; size?: 'sm' | 'md'; icon?: LucideIcon; loading?: boolean
}
export function Button({ variant = 'secondary', size = 'md', icon: Icon, loading, className, children, disabled, ...rest }: BtnProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cn(
        'inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md font-medium whitespace-nowrap transition-colors disabled:opacity-45',
        size === 'sm' ? 'h-7 px-2.5 text-xs' : 'h-8 px-3 text-sm',
        variant === 'primary' && 'bg-accent-strong text-accent-fg shadow-[inset_0_1px_0_rgb(255_255_255/0.15)] hover:brightness-110',
        variant === 'secondary' && 'border border-line-strong bg-panel text-fg hover:bg-raised',
        variant === 'ghost' && 'text-muted hover:bg-raised hover:text-fg',
        variant === 'danger' && 'border border-bad/40 bg-bad/10 text-bad hover:bg-bad/15',
        className,
      )}
    >
      {loading ? <Loader2 className="size-3.5 animate-spin" /> : Icon && <Icon className="size-3.5" />}
      {children}
    </button>
  )
}

/** A button gated by a permission: disabled with an explanation when the current role cannot act. */
export function Act({ perm, block, className, ...props }: BtnProps & { perm: string; block?: boolean }) {
  const { can, role } = useSession()
  const cls = cn(block && 'w-full', className)
  if (can(perm)) return <Button {...props} className={cls} />
  return (
    <Tip text={`${role.label} role can’t ${PERMS[perm] ?? perm}`} align="end" className={cn(block && 'flex w-full')}>
      <Button {...props} className={cls} disabled onClick={undefined} />
    </Tip>
  )
}

export function Tip({ text, children, side = 'top', align = 'center', className }: {
  text: ReactNode; children: ReactNode; side?: 'top' | 'bottom'; align?: 'center' | 'end'; className?: string
}) {
  return (
    <span className={cn('group/tip relative inline-flex', className)}>
      {children}
      <span
        role="tooltip"
        className={cn(
          'pointer-events-none absolute z-50 hidden rounded-md border border-line-strong bg-raised px-2 py-1 text-xs whitespace-nowrap text-fg shadow-pop group-hover/tip:block',
          side === 'top' ? 'bottom-full mb-1.5' : 'top-full mt-1.5',
          align === 'center' ? 'left-1/2 -translate-x-1/2' : 'right-0',
        )}
      >
        {text}
      </span>
    </span>
  )
}

/* ------------------------------------------------------------------ pills & badges */
const TONES: Record<Tone, string> = {
  neutral: 'border-line-strong bg-raised text-muted',
  accent: 'border-accent/30 bg-accent/10 text-accent',
  ok: 'border-ok/30 bg-ok/10 text-ok',
  warn: 'border-warn/30 bg-warn/10 text-warn',
  bad: 'border-bad/30 bg-bad/10 text-bad',
}
export function Pill({ tone = 'neutral', dot, pulse, icon: Icon, children, className, title }: {
  tone?: Tone; dot?: boolean; pulse?: boolean; icon?: LucideIcon; children: ReactNode; className?: string; title?: string
}) {
  return (
    <span title={title} className={cn('inline-flex h-5 max-w-full items-center gap-1 rounded-full border px-1.5 text-2xs font-medium whitespace-nowrap', TONES[tone], className)}>
      {dot && <span className={cn('size-1.5 shrink-0 rounded-full bg-current', pulse && 'animate-ping-soft')} />}
      {Icon && <Icon className="size-3 shrink-0" />}
      <span className="truncate">{children}</span>
    </span>
  )
}
export const StatusPill = ({ status }: { status: TaskStatus }) => {
  const m = TASK_STATUS[status] ?? { label: status, tone: 'neutral' as Tone }
  return <Pill tone={m.tone} dot pulse={status === 'running'}>{m.label}</Pill>
}
const AUTONOMY_ICON: [LucideIcon, Tone][] = [[Eye, 'neutral'], [ShieldCheck, 'warn'], [Zap, 'ok']]
export function AutonomyBadge({ level, label }: { level: number; label: string }) {
  const [Icon, tone] = AUTONOMY_ICON[level] ?? AUTONOMY_ICON[0]
  return <Pill tone={tone} icon={Icon}>{label}</Pill>
}
export const Kbd = ({ children, className }: { children: ReactNode; className?: string }) => (
  <kbd className={cn('inline-flex h-[18px] min-w-[18px] items-center justify-center rounded border border-line-strong bg-raised px-1 font-sans text-2xs text-subtle', className)}>{children}</kbd>
)
export const Mono = ({ children, className }: { children: ReactNode; className?: string }) => (
  <span className={cn('font-mono text-xs text-muted', className)}>{children}</span>
)

/* ------------------------------------------------------------------ identity */
export const SectorDot = ({ sector, className }: { sector?: string; className?: string }) => (
  <span className={cn('inline-block size-2 shrink-0 rounded-full', className)} style={{ background: sectorMeta(sector).color }} />
)
export function Avatar({ emp, size = 'md' }: { emp: Pick<Employee, 'name' | 'sector' | 'avatar_initials'>; size?: 'sm' | 'md' | 'lg' }) {
  const color = sectorMeta(emp.sector).color
  return (
    <span
      className={cn('inline-flex shrink-0 items-center justify-center rounded-md font-semibold text-white',
        size === 'sm' && 'size-5 text-2xs', size === 'md' && 'size-7 text-xs', size === 'lg' && 'size-11 rounded-lg text-base')}
      style={{ background: `linear-gradient(140deg, color-mix(in oklab, ${color} 92%, white), color-mix(in oklab, ${color} 80%, black))` }}
    >
      {emp.avatar_initials || emp.name.slice(0, 1)}
    </span>
  )
}
export const LogoMark = ({ className }: { className?: string }) => (
  <svg viewBox="0 0 24 24" className={cn('size-6', className)} aria-hidden>
    <rect width="24" height="24" rx="6" fill="var(--accent-strong)" />
    <circle cx="7.5" cy="7.5" r="2.25" fill="#fff" />
    <path d="M7.5 9.75v2.5a2.5 2.5 0 0 0 2.5 2.5h4" stroke="#fff" strokeWidth="1.75" fill="none" strokeLinecap="round" />
    <rect x="14" y="12.5" width="4.5" height="4.5" rx="1.25" fill="#fff" />
  </svg>
)

/* ------------------------------------------------------------------ layout */
export const Panel = ({ className, children }: { className?: string; children: ReactNode }) => (
  <section className={cn('rounded-lg border border-line bg-panel', className)}>{children}</section>
)
export function PanelHead({ title, hint, actions, className }: { title: ReactNode; hint?: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <header className={cn('flex min-h-11 items-center gap-3 border-b border-line px-4 py-2', className)}>
      <div className="min-w-0 flex-1">
        <h3 className="truncate text-sm font-semibold">{title}</h3>
        {hint && <p className="truncate text-xs text-subtle">{hint}</p>}
      </div>
      {actions}
    </header>
  )
}
export function PageHeader({ title, subtitle, actions, children }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children?: ReactNode }) {
  return (
    <div className="border-b border-line bg-panel/40 px-6 pt-5">
      <div className="flex items-start gap-4 pb-4">
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
      {children}
    </div>
  )
}
export function Tabs<T extends string>({ tabs, value, onChange, className }: {
  tabs: { id: T; label: string; count?: number; icon?: LucideIcon }[]; value: T; onChange: (v: T) => void; className?: string
}) {
  return (
    <nav className={cn('-mb-px flex gap-5', className)} role="tablist">
      {tabs.map(({ id, label, count, icon: Icon }) => (
        <button key={id} role="tab" aria-selected={value === id} onClick={() => onChange(id)}
          className={cn('flex h-9 items-center gap-1.5 border-b-2 text-sm transition-colors',
            value === id ? 'border-accent font-medium text-fg' : 'border-transparent text-muted hover:text-fg')}>
          {Icon && <Icon className="size-3.5" />}
          {label}
          {count != null && <span className="rounded bg-raised px-1 text-2xs text-muted tnum">{count}</span>}
        </button>
      ))}
    </nav>
  )
}
export function Segmented<T extends string>({ options, value, onChange }: { options: { id: T; label: string }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex h-7 items-center rounded-md border border-line bg-sunken p-0.5">
      {options.map((o) => (
        <button key={o.id} onClick={() => onChange(o.id)}
          className={cn('h-full rounded px-2.5 text-xs transition-colors', value === o.id ? 'bg-raised font-medium text-fg shadow-sm ring-1 ring-line-strong' : 'text-muted hover:text-fg')}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------------ data bits */
export function Stat({ label, value, hint, icon: Icon }: { label: string; value: ReactNode; hint?: ReactNode; icon?: LucideIcon }) {
  return (
    <div className="min-w-0 px-4 py-3.5">
      <div className="flex items-center gap-1.5 text-xs text-muted">{Icon && <Icon className="size-3.5 text-subtle" />}{label}</div>
      <div className="mt-1 truncate text-2xl font-semibold tracking-tight tnum">{value}</div>
      {hint && <div className="mt-0.5 truncate text-xs text-subtle">{hint}</div>}
    </div>
  )
}
export function Meter({ value, tone = 'accent', className }: { value: number; tone?: Tone; className?: string }) {
  const bg = { accent: 'bg-accent', ok: 'bg-ok', warn: 'bg-warn', bad: 'bg-bad', neutral: 'bg-subtle' }[tone]
  return (
    <div className={cn('h-1.5 w-full overflow-hidden rounded-full bg-raised', className)}>
      <div className={cn('h-full rounded-full transition-[width] duration-500', bg)} style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} />
    </div>
  )
}
export const confidenceTone = (c: number): Tone => (c >= 0.9 ? 'ok' : c >= 0.7 ? 'warn' : 'bad')
export function Switch({ checked, onChange, disabled, label }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; label?: string }) {
  return (
    <button role="switch" aria-checked={checked} aria-label={label} disabled={disabled} onClick={() => onChange(!checked)}
      className={cn('relative h-[18px] w-8 shrink-0 rounded-full border transition-colors disabled:opacity-45',
        checked ? 'border-accent-strong bg-accent-strong' : 'border-line-strong bg-raised')}>
      <span className={cn('absolute top-px size-3.5 rounded-full bg-white shadow transition-[left]', checked ? 'left-[15px]' : 'left-px')} />
    </button>
  )
}
const field = 'w-full rounded-md border border-line-strong bg-sunken px-2.5 text-sm text-fg placeholder:text-subtle focus:border-accent focus:outline-none disabled:opacity-60'
export const Input = ({ className, ...p }: InputHTMLAttributes<HTMLInputElement>) => <input {...p} className={cn(field, 'h-8', className)} />
export const Textarea = ({ className, ...p }: TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...p} className={cn(field, 'py-2', className)} />
export const Select = ({ className, ...p }: SelectHTMLAttributes<HTMLSelectElement>) => <select {...p} className={cn(field, 'h-8 pr-7', className)} />
export const Label = ({ children, hint }: { children: ReactNode; hint?: ReactNode }) => (
  <div className="mb-1.5 flex items-baseline justify-between gap-2 text-xs font-medium text-muted">{children}{hint && <span className="font-normal text-subtle">{hint}</span>}</div>
)

/* ------------------------------------------------------------------ states */
export const Skeleton = ({ className }: { className?: string }) => <div className={cn('animate-shimmer rounded-md bg-raised', className)} />
export function Empty({ icon: Icon, title, body, action, className }: { icon: LucideIcon; title: string; body?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cn('flex flex-col items-center justify-center px-6 py-12 text-center', className)}>
      <div className="mb-3 flex size-9 items-center justify-center rounded-lg border border-line bg-raised text-subtle"><Icon className="size-4" /></div>
      <p className="text-sm font-medium">{title}</p>
      {body && <p className="mt-1 max-w-sm text-xs text-muted">{body}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
export function ErrorNote({ error, retry, className }: { error: unknown; retry?: () => void; className?: string }) {
  const down = !(error instanceof ApiError) || error.status >= 502
  return (
    <Empty className={className} icon={AlertTriangle} title={down ? 'Can’t reach the API' : 'Couldn’t load this'}
      body={down ? 'The backend isn’t responding. Check that it is running on :8000 — this view retries automatically.' : (error as Error).message}
      action={retry && <Button size="sm" onClick={retry}>Try again</Button>} />
  )
}
/** Renders loading / error states for a query, then the children with data. */
export function Load<T>({ q, children, skeleton }: { q: Pick<UseQueryResult<T>, 'data' | 'error' | 'isLoading' | 'refetch'>; children: (d: T) => ReactNode; skeleton?: ReactNode }) {
  if (q.data !== undefined) return <>{children(q.data)}</>
  if (q.error) return <ErrorNote error={q.error} retry={() => void q.refetch()} />
  return <>{skeleton ?? <div className="space-y-2 p-4"><Skeleton className="h-4 w-1/3" /><Skeleton className="h-4 w-2/3" /><Skeleton className="h-4 w-1/2" /></div>}</>
}

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }
  static getDerivedStateFromError(error: Error) { return { error } }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error(error, info.componentStack) }
  render() {
    if (!this.state.error) return this.props.children
    return (
      <Empty icon={AlertTriangle} title="This view hit an error" body={this.state.error.message} className="h-full"
        action={<Button size="sm" onClick={() => this.setState({ error: null })}>Reload view</Button>} />
    )
  }
}
