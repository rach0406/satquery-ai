import { Suspense, lazy } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from './lib/auth.jsx'
import { Logo } from './components/Brand'
import Landing from './pages/Landing'

/* The console pulls in Leaflet and Plotly. Keeping it behind a lazy boundary
   means a visitor who only reads the landing page never downloads them. */
const Console = lazy(() => import('./pages/Console'))
const Auth = lazy(() => import('./pages/Auth'))

function Booting({ label = 'Loading SatQuery AI' }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-5 bg-paper-100">
      <span className="animate-pulseSoft">
        <Logo size={44} />
      </span>
      <p className="text-small font-medium text-ink-400">{label}</p>
    </div>
  )
}

/** Gate for the console. Sends an unauthenticated visitor to sign-in and
 *  remembers where they were headed so login returns them there. */
function RequireAuth({ children }) {
  const { isAuthenticated, ready } = useAuth()
  const location = useLocation()

  if (!ready) return <Booting label="Restoring your session" />
  if (!isAuthenticated) return <Navigate to="/login" replace state={{ from: location }} />
  return children
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Suspense fallback={<Booting />}>
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/login" element={<Auth />} />
            <Route path="/signup" element={<Navigate to="/login?mode=signup" replace />} />
            <Route
              path="/app"
              element={
                <RequireAuth>
                  <Console />
                </RequireAuth>
              }
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </AuthProvider>
  )
}
