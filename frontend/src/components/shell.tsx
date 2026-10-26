import { Suspense, useEffect, useRef, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  ArrowRight, Check, ChevronDown, Flame, Inbox, LayoutDashboard, ListChecks, Moon, ScrollText, Search, Settings2, Sun, UserPlus, Users,
  type LucideIcon,
} from 'lucide-react'
import { api, useAction, useEmployees, useHealth, useInbox, useSession, useSettings, useTemplates, useWorkspace } from '../lib/api'
import { cn, registerSectors, sectorMeta, sortEmployees } from '../lib/format'
import { CommandPalette, openPalette } from './command-palette'
import { ErrorBoundary, Kbd, LogoMark, Pill, SectorDot, Skeleton, Switch, Tip } from './ui'

const NAV: { to: string; label: string; icon: LucideIcon; end?: boolean }[] = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/employees', label: 'Workforce', icon: Users },
  { to: '/work', label: 'Work queue', icon: ListChecks },
  { to: '/inbox', label: 'Inbox', icon: Inbox },
  { to: '/hire', label: 'Hire', icon: UserPlus },
  { to: '/audit', label: 'Audit', icon: ScrollText },
  { to: '/settings', label: 'Settings', icon: Settings2 },
]

export function Shell() {
  const loc = useLocation()
  const templates = useTemplates()
  const emps = useEmployees()
  const ready = !templates.isLoading
  // Template-library order fixes each sector's colour slot; sectors only seen on employees come after.
  if (ready) registerSectors([...(templates.data ?? []).map((t) => t.sector), ...(emps.data ?? []).map((e) => e.sector)])
  return (
    <div className="flex h-full overflow-hidden">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        <main className="min-h-0 flex-1 overflow-auto">
          <ErrorBoundary key={loc.pathname}>
            <Suspense fallback={<div className="space-y-3 p-6"><Skeleton className="h-8 w-64" /><Skeleton className="h-[60vh]" /></div>}>
              {ready && <div className="h-full animate-in"><Outlet /></div>}
            </Suspense>
          </ErrorBoundary>
        </main>
      </div>
      <CommandPalette />
    </div>
  )
}

const navCls = ({ isActive }: { isActive: boolean }) =>
  cn('group flex h-7 items-center gap-2 rounded-md px-2 text-sm transition-colors',
    isActive ? 'bg-raised font-medium text-fg ring-1 ring-line' : 'text-muted hover:bg-raised/60 hover:text-fg')

function Sidebar() {
  const inbox = useInbox()
  const emps = useEmployees()
  const templates = useTemplates()
  const ws = useWorkspace()
  const unhired = (templates.data ?? []).filter((t) => !t.hired_count)
  const open = inbox.data?.length ?? 0
  return (
    <aside className="flex w-[232px] shrink-0 flex-col border-r border-line bg-panel/50">
      <div className="flex h-12 items-center gap-2 border-b border-line px-3.5">
        <LogoMark />
        <span className="text-[15px] font-semibold tracking-tight">Prompt2Process</span>
      </div>
      <div className="p-2.5">
        <button onClick={openPalette}
          className="flex h-8 w-full items-center gap-2 rounded-md border border-line bg-sunken px-2.5 text-sm text-subtle transition-colors hover:border-line-strong hover:text-muted">
          <Search className="size-3.5" /> <span className="flex-1 text-left">Search or jump to…</span> <Kbd>⌘K</Kbd>
        </button>
      </div>
      <nav className="space-y-px px-2.5">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end} className={navCls}>
            {({ isActive }) => (
              <>
                <Icon className={cn('size-4', isActive ? 'text-accent' : 'text-subtle')} />
                <span className="flex-1">{label}</span>
                {to === '/inbox' && open > 0 && (
                  <span className="rounded-full bg-accent-strong px-1.5 text-2xs font-semibold text-accent-fg tnum">{open}</span>
                )}
              </>
            )}
          </NavLink>
        ))}
      </nav>
      {ws.data && !ws.data.setup_complete && (
        <Link to={ws.data.org?.name ? '/hire' : '/'} className="mx-2.5 mt-4 block rounded-lg border border-accent/30 bg-accent/10 p-3 hover:bg-accent/15">
          <div className="text-sm font-medium text-fg">Finish setting up</div>
          <p className="mt-0.5 text-xs text-muted">{ws.data.org?.name ? 'Hire your first digital employee.' : 'Add your company profile and approvers, then hire.'}</p>
          <span className="mt-2 flex items-center gap-1 text-xs font-medium text-accent">Continue <ArrowRight className="size-3" /></span>
        </Link>
      )}
      <div className="mt-5 min-h-0 flex-1 overflow-y-auto px-2.5">
        <div className="px-2 pb-1.5 text-2xs font-medium tracking-wider text-subtle uppercase">Sectors</div>
        <div className="space-y-px">
          {sortEmployees(emps.data ?? []).map((e) => (
            <NavLink key={e.id} to={`/employees/${e.id}`} className={navCls}>
              <SectorDot sector={e.sector} />
              <span className="flex-1 truncate">{sectorMeta(e.sector).short}</span>
              <span className="max-w-20 truncate text-xs text-subtle">{e.name}</span>
            </NavLink>
          ))}
          {unhired.map((t) => (
            <Link key={t.id} to={`/hire?template=${t.id}`} title={`${t.employee.title} — not hired yet`}
              className="flex h-7 items-center gap-2 rounded-md px-2 text-sm text-subtle hover:bg-raised/60 hover:text-muted">
              <span className="inline-block size-2 shrink-0 rounded-full border border-current" style={{ color: sectorMeta(t.sector).color }} />
              <span className="flex-1 truncate">{t.department}</span>
              <span className="text-xs">+ Hire</span>
            </Link>
          ))}
          {emps.data?.length === 0 && unhired.length === 0 && <p className="px-2 text-xs text-subtle">No employees yet.</p>}
        </div>
      </div>
      <SidebarFooter />
    </aside>
  )
}

function SidebarFooter() {
  const { role } = useSession()
  return (
    <div className="border-t border-line p-3">
      <div className="text-2xs font-medium tracking-wider text-subtle uppercase">Viewing as</div>
      <div className="mt-0.5 text-sm font-medium">{role.label}</div>
      <p className="text-xs leading-snug text-subtle">{role.about}</p>
    </div>
  )
}

const TITLES: [RegExp, string][] = [
  [/^\/employees\/.+/, 'Workforce'], [/^\/employees/, 'Workforce'], [/^\/work/, 'Work queue'], [/^\/inbox/, 'Inbox'],
  [/^\/hire/, 'Hire'], [/^\/audit/, 'Audit'], [/^\/settings/, 'Settings'], [/^\/setup/, 'Setup'], [/^\/$/, 'Overview'],
]

function Topbar() {
  const { pathname } = useLocation()
  const ws = useWorkspace()
  const { theme, toggleTheme } = useSession()
  const section = TITLES.find(([re]) => re.test(pathname))?.[1] ?? ''
  const name = ws.data?.org?.name || 'New workspace'
  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line bg-panel/50 px-4">
      <div className="flex min-w-0 items-center gap-2 text-sm">
        <span className="flex size-5 items-center justify-center rounded bg-raised text-2xs font-semibold text-muted ring-1 ring-line-strong">{name[0]}</span>
        <span className="truncate font-medium">{name}</span>
        <span className="text-subtle">/</span>
        <span className="truncate text-muted">{section}</span>
      </div>
      <div className="ml-auto flex items-center gap-2">
        <GemmaPill />
        <ChaosToggle />
        <span className="mx-1 h-5 w-px bg-line" />
        <RoleSwitcher />
        <Tip text={theme === 'dark' ? 'Light theme' : 'Dark theme'} side="bottom">
          <button onClick={toggleTheme} aria-label="Toggle theme"
            className="flex size-8 items-center justify-center rounded-md text-muted hover:bg-raised hover:text-fg">
            {theme === 'dark' ? <Sun className="size-4" /> : <Moon className="size-4" />}
          </button>
        </Tip>
      </div>
    </header>
  )
}

function GemmaPill() {
  const h = useHealth()
  if (h.error) return <Pill tone="bad" dot>API offline</Pill>
  if (!h.data) return <Pill dot>Connecting…</Pill>
  const live = h.data.llm_mode === 'live'
  return (
    <Tip side="bottom" text={live ? `${h.data.model} · vision ${h.data.vision_model}` : h.data.llm_error || 'Deterministic fallbacks active'}>
      <Pill tone={live ? 'ok' : 'neutral'} dot pulse={live}>Gemma 4 · {live ? 'live' : 'offline'}</Pill>
    </Tip>
  )
}

function ChaosToggle() {
  const s = useSettings()
  const { can, role } = useSession()
  const set = useAction((v: boolean) => api.put('/settings', { chaos_mode: v }), {
    success: (_, v) => (v ? 'Chaos mode on — steps will fail at random' : 'Chaos mode off'),
  })
  const on = !!s.data?.chaos_mode
  const allowed = can('settings.edit')
  return (
    <Tip side="bottom" text={allowed ? `Inject random step failures (${Math.round((s.data?.chaos_rate ?? 0) * 100)}% rate)` : `${role.label} role can’t change settings`}>
      <label className={cn('flex h-7 items-center gap-2 rounded-md border px-2 text-xs', on ? 'border-warn/40 bg-warn/10 text-warn' : 'border-line text-muted')}>
        <Flame className="size-3.5" /> Chaos
        <Switch checked={on} disabled={!allowed || !s.data || set.isPending} onChange={(v) => set.mutate(v)} label="Chaos mode" />
      </label>
    </Tip>
  )
}

function RoleSwitcher() {
  const { role, roles, setRole } = useSession()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !ref.current?.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener('mousedown', close)
    window.addEventListener('keydown', close)
    return () => { window.removeEventListener('mousedown', close); window.removeEventListener('keydown', close) }
  }, [open])
  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open}
        className="flex h-8 items-center gap-1.5 rounded-md border border-line-strong bg-panel px-2.5 text-sm hover:bg-raised">
        <span className="text-subtle">View as</span><span className="font-medium">{role.label}</span>
        <ChevronDown className="size-3.5 text-subtle" />
      </button>
      {open && (
        <div role="menu" className="absolute top-full right-0 z-50 mt-1.5 w-80 animate-pop rounded-lg border border-line-strong bg-panel p-1 shadow-pop">
          {roles.map((r) => (
            <button key={r.id} role="menuitemradio" aria-checked={r.id === role.id}
              onClick={() => { setRole(r.id); setOpen(false) }}
              className="flex w-full items-start gap-2.5 rounded-md px-2.5 py-2 text-left hover:bg-raised">
              <Check className={cn('mt-0.5 size-3.5 shrink-0 text-accent', r.id !== role.id && 'invisible')} />
              <span className="min-w-0">
                <span className="block text-sm font-medium">{r.label}</span>
                <span className="block text-xs text-muted">{r.about}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
