import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { useQueryClient } from '@tanstack/react-query'
import {
  ArrowRight, CornerDownLeft, FileText, FlaskConical, Flame, Inbox, LayoutDashboard, ListChecks, Play, ScrollText, Search,
  Settings2, SunMoon, Download, UserCog, UserPlus, Users, type LucideIcon,
} from 'lucide-react'
import { api, toastError, useEmployees, useSession, useSettings, useTasks, useTemplates } from '../lib/api'
import { cn, PERMS, sortEmployees } from '../lib/format'
import { Avatar, Kbd } from './ui'

const EVT = 'p2p:palette'
const GROUPS = ['Go to', 'Employees', 'Actions', 'Hire', 'View as', 'Cases']
export const openPalette = () => window.dispatchEvent(new Event(EVT))

type Item = { id: string; group: string; label: string; hint?: string; icon?: LucideIcon; avatar?: Parameters<typeof Avatar>[0]['emp']; perm?: string; run: () => void | Promise<unknown> }

export function CommandPalette() {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setOpen((o) => !o) }
    }
    const onOpen = () => setOpen(true)
    window.addEventListener('keydown', onKey)
    window.addEventListener(EVT, onOpen)
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener(EVT, onOpen) }
  }, [])
  return open ? <Palette close={() => setOpen(false)} /> : null
}

function Palette({ close }: { close: () => void }) {
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const listRef = useRef<HTMLDivElement>(null)
  const nav = useNavigate()
  const qc = useQueryClient()
  const { can, role, roles, setRole, toggleTheme, theme } = useSession()
  const emps = useEmployees()
  const tasks = useTasks()
  const settings = useSettings()
  const templates = useTemplates()

  const items = useMemo<Item[]>(() => {
    const act = async (fn: () => Promise<unknown>, ok: string) => {
      try { await fn(); toast.success(ok); void qc.invalidateQueries() } catch (e) { toastError(e) }
    }
    const pages: [string, string, LucideIcon][] = [
      ['/', 'Overview', LayoutDashboard], ['/employees', 'Workforce', Users], ['/work', 'Work queue', ListChecks],
      ['/inbox', 'Inbox', Inbox], ['/hire', 'Hire from an SOP', UserPlus], ['/audit', 'Audit trail', ScrollText], ['/settings', 'Settings', Settings2],
    ]
    const list: Item[] = pages.map(([to, label, icon]) => ({ id: `nav${to}`, group: 'Go to', label, icon, run: () => nav(to) }))
    for (const e of sortEmployees(emps.data ?? [])) {
      list.push({ id: `emp-${e.id}`, group: 'Employees', label: `${e.name} — ${e.role_title ?? e.role}`, hint: e.sector, avatar: e, run: () => nav(`/employees/${e.id}`) })
      list.push(
        { id: `bt-${e.id}`, group: 'Actions', label: `Run backtest for ${e.name}`, icon: FlaskConical, perm: 'backtest.run',
          run: async () => { nav(`/employees/${e.id}?tab=backtest`); await act(() => api.post(`/employees/${e.id}/backtest`), `Backtest started for ${e.name}`) } },
        { id: `in-${e.id}`, group: 'Actions', label: `Ingest new work for ${e.name}`, icon: Download, perm: 'work.run',
          run: () => act(() => api.post(`/employees/${e.id}/ingest`), `Checked ${e.name}’s inbox for new work`) },
        { id: `run-${e.id}`, group: 'Actions', label: `Run ${e.name}’s queue`, icon: Play, perm: 'work.run',
          run: () => act(() => api.post(`/employees/${e.id}/run`, {}), `${e.name} is working the queue`) },
      )
    }
    list.push(
      { id: 'chaos', group: 'Actions', label: `Turn chaos mode ${settings.data?.chaos_mode ? 'off' : 'on'}`, icon: Flame, perm: 'settings.edit',
        run: () => act(() => api.put('/settings', { chaos_mode: !settings.data?.chaos_mode }), 'Chaos mode updated') },
      { id: 'theme', group: 'Actions', label: `Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`, icon: SunMoon, run: toggleTheme },
    )
    for (const t of templates.data ?? []) list.push({ id: `hire-${t.id}`, group: 'Hire', label: `Hire a ${t.employee.title}`, hint: t.sector, icon: UserPlus, perm: 'hire', run: () => nav(`/hire?template=${t.id}`) })
    for (const r of roles) if (r.id !== role.id) list.push({ id: `role-${r.id}`, group: 'View as', label: `View as ${r.label}`, hint: r.about, icon: UserCog, run: () => setRole(r.id) })
    for (const t of (tasks.data ?? []).slice(0, 40)) list.push({ id: `task-${t.id}`, group: 'Cases', label: t.title, hint: t.id, icon: FileText, run: () => nav(`/work/${t.id}`) })
    return list.sort((a, b) => GROUPS.indexOf(a.group) - GROUPS.indexOf(b.group)) // stable: keeps order within a group
  }, [emps.data, tasks.data, settings.data, templates.data, roles, role.id, theme, nav, qc, setRole, toggleTheme])

  const filtered = useMemo(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean)
    if (words.length) return items.filter((i) => words.every((w) => `${i.group} ${i.label} ${i.hint ?? ''}`.toLowerCase().includes(w)))
    const firstCase = items.findIndex((x) => x.group === 'Cases')
    return firstCase < 0 ? items : items.slice(0, firstCase + 6)
  }, [items, query])

  useEffect(() => { listRef.current?.querySelector(`[data-i="${active}"]`)?.scrollIntoView({ block: 'nearest' }) }, [active])

  const choose = (i?: Item) => {
    if (!i || (i.perm && !can(i.perm))) return
    close()
    void i.run()
  }
  const onKey = (e: ReactKeyEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(filtered.length - 1, a + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(0, a - 1)) }
    else if (e.key === 'Enter') { e.preventDefault(); choose(filtered[active]) }
    else if (e.key === 'Escape') close()
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center bg-black/50 pt-[12vh] backdrop-blur-[2px]" onMouseDown={close}>
      <div className="w-[640px] max-w-[calc(100vw-32px)] animate-pop overflow-hidden rounded-xl border border-line-strong bg-panel shadow-pop" onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex h-12 items-center gap-2.5 border-b border-line px-4">
          <Search className="size-4 text-subtle" />
          <input autoFocus value={query} onChange={(e) => { setQuery(e.target.value); setActive(0) }} onKeyDown={onKey}
            placeholder="Search pages, employees, cases or actions…" className="h-full flex-1 bg-transparent text-base outline-none placeholder:text-subtle" />
          <Kbd>esc</Kbd>
        </div>
        <div ref={listRef} className="max-h-[420px] overflow-y-auto p-1.5">
          {filtered.length === 0 && <p className="px-3 py-10 text-center text-sm text-muted">No matches for “{query}”.</p>}
          {filtered.map((it, idx) => {
            const head = idx === 0 || filtered[idx - 1].group !== it.group ? it.group : null
            const blocked = !!it.perm && !can(it.perm)
            return (
              <div key={it.id}>
                {head && <div className="px-2.5 pt-2.5 pb-1 text-2xs font-medium tracking-wider text-subtle uppercase">{head}</div>}
                <button data-i={idx} onMouseMove={() => setActive(idx)} onClick={() => choose(it)} disabled={blocked}
                  className={cn('flex h-9 w-full items-center gap-2.5 rounded-md px-2.5 text-left text-sm', idx === active && 'bg-raised', blocked && 'opacity-50')}>
                  {it.avatar ? <Avatar emp={it.avatar} size="sm" /> : it.icon && <it.icon className="size-4 shrink-0 text-subtle" />}
                  <span className="min-w-0 flex-1 truncate">{it.label}</span>
                  {blocked ? <span className="text-xs text-subtle">{role.label} can’t {PERMS[it.perm!]}</span>
                    : it.hint && <span className="max-w-[45%] truncate font-mono text-2xs text-subtle">{it.hint}</span>}
                  {idx === active && !blocked && <ArrowRight className="size-3.5 text-subtle" />}
                </button>
              </div>
            )
          })}
        </div>
        <div className="flex items-center gap-4 border-t border-line px-4 py-2 text-xs text-subtle">
          <span className="flex items-center gap-1"><Kbd>↑</Kbd><Kbd>↓</Kbd> navigate</span>
          <span className="flex items-center gap-1"><Kbd><CornerDownLeft className="size-3" /></Kbd> select</span>
          <span className="ml-auto">Viewing as {role.label}</span>
        </div>
      </div>
    </div>
  )
}
