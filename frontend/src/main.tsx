import { lazy, StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'sonner'
import { Compass } from 'lucide-react'
import '@fontsource-variable/inter'
import '@fontsource-variable/jetbrains-mono'
import '@fontsource/noto-sans-devanagari/400.css'
import '@fontsource/noto-sans-telugu/400.css'
import './index.css'
import { SessionProvider, useSession } from './lib/api'
import { Shell } from './components/shell'
import { Empty, ErrorBoundary } from './components/ui'

// Pages are code-split: charts (recharts) and the graph editor (@xyflow) load only where used.
const OverviewPage = lazy(() => import('./pages/overview').then((m) => ({ default: m.OverviewPage })))
const WorkforcePage = lazy(() => import('./pages/workforce').then((m) => ({ default: m.WorkforcePage })))
const EmployeePage = lazy(() => import('./pages/workforce').then((m) => ({ default: m.EmployeePage })))
const WorkPage = lazy(() => import('./pages/work').then((m) => ({ default: m.WorkPage })))
const CasePage = lazy(() => import('./pages/case').then((m) => ({ default: m.CasePage })))
const InboxPage = lazy(() => import('./pages/inbox').then((m) => ({ default: m.InboxPage })))
const HirePage = lazy(() => import('./pages/hire').then((m) => ({ default: m.HirePage })))
const AuditPage = lazy(() => import('./pages/audit').then((m) => ({ default: m.AuditPage })))
const SettingsPage = lazy(() => import('./pages/settings').then((m) => ({ default: m.SettingsPage })))
const SetupPage = lazy(() => import('./pages/setup').then((m) => ({ default: m.SetupPage })))

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 1000 } },
})

function App() {
  const { theme } = useSession()
  return (
    <>
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<OverviewPage />} />
          <Route path="employees" element={<WorkforcePage />} />
          <Route path="employees/:id" element={<EmployeePage />} />
          <Route path="work" element={<WorkPage />} />
          <Route path="work/:id" element={<CasePage />} />
          <Route path="inbox" element={<InboxPage />} />
          <Route path="hire" element={<HirePage />} />
          <Route path="audit" element={<AuditPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="setup" element={<SetupPage />} />
          <Route path="*" element={<Empty icon={Compass} title="Page not found" body="Use ⌘K to jump anywhere." className="h-full" />} />
        </Route>
      </Routes>
      <Toaster theme={theme} position="bottom-left" offset={16} closeButton
        toastOptions={{ classNames: { toast: '!bg-panel !border-line-strong !text-fg !font-sans !text-sm !shadow-pop', description: '!text-muted' } }} />
    </>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <SessionProvider>
            <App />
          </SessionProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
)
