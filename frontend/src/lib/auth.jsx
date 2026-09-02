import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

const BASE = import.meta.env.VITE_API_BASE || ''
const STORAGE_KEY = 'satquery.session'

/* The token is a signed, expiring credential issued by the backend — the
   client only caches it. Every protected call re-presents it and the server
   re-verifies the signature, so a tampered localStorage entry buys nothing. */
function readStored() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const s = JSON.parse(raw)
    if (!s?.token || !s?.expires_at) return null
    if (s.expires_at * 1000 <= Date.now()) {
      localStorage.removeItem(STORAGE_KEY)
      return null
    }
    return s
  } catch {
    return null
  }
}

function writeStored(session) {
  try {
    if (session) localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* private browsing — the session simply lasts for this tab only */
  }
}

/* Turn any failure — a rejected credential, a validation error, an unreachable
   backend — into one sentence a person can act on.

   `detail` is normally a string. FastAPI's validation errors make it a list of
   objects, and a proxy that cannot reach the API returns HTML with no JSON at
   all; both used to surface on the sign-in form as "[object Object]" or a bare
   "500 Internal Server Error" with nothing to do about it. */
function describeFailure(status, statusText, data) {
  const d = data?.detail
  if (typeof d === 'string' && d.trim()) return d
  if (Array.isArray(d) && d.length) {
    return d
      .map((e) => {
        const field = (e.loc || []).filter((p) => p !== 'body').join(' → ')
        return field ? `${field}: ${e.msg}` : e.msg
      })
      .join('; ')
  }
  if (status === 0) {
    return 'Cannot reach the SatQuery AI backend. Start it with "uvicorn app.main:app --port 8000" and try again.'
  }
  if (status >= 500) {
    return `The server could not complete the request (${status}). Check the backend window for the error, then try again.`
  }
  return `${status} ${statusText || 'Request failed'}`
}

async function post(path, body) {
  let r
  try {
    r = await fetch(`${BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    throw new Error(describeFailure(0, '', null))
  }
  const data = await r.json().catch(() => null)
  if (!r.ok) throw new Error(describeFailure(r.status, r.statusText, data))
  return data ?? {}
}

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [session, setSession] = useState(() => readStored())
  const [config, setConfig] = useState(null)
  const [ready, setReady] = useState(false)

  // Validate a cached session against the server on boot, and pick up the
  // auth policy (demo credentials, password rules) for the sign-in screen.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetch(`${BASE}/api/auth/config`)
        if (r.ok && !cancelled) setConfig(await r.json())
      } catch {
        /* backend down — the UI shows its own offline notice */
      }
      const stored = readStored()
      if (stored) {
        try {
          const r = await fetch(`${BASE}/api/auth/me`, {
            headers: { Authorization: `Bearer ${stored.token}` },
          })
          if (!r.ok) throw new Error('stale')
          const data = await r.json()
          if (!cancelled) setSession({ ...stored, user: data.user })
        } catch {
          writeStored(null)
          if (!cancelled) setSession(null)
        }
      }
      if (!cancelled) setReady(true)
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (username, password) => {
    const data = await post('/api/auth/login', { username, password })
    const s = { token: data.token, expires_at: data.expires_at, user: data.user }
    writeStored(s)
    setSession(s)
    return s
  }, [])

  const signup = useCallback(async (payload) => {
    const data = await post('/api/auth/signup', payload)
    const s = { token: data.token, expires_at: data.expires_at, user: data.user }
    writeStored(s)
    setSession(s)
    return s
  }, [])

  /* Ask the server whether a username is free, so the sign-up form can say so
     before the user has finished filling in the rest of it. Never throws — an
     unreachable backend simply means the form falls back to reporting the
     clash on submit. */
  const checkUsername = useCallback(async (username) => {
    try {
      return await post('/api/auth/check-username', { username })
    } catch {
      return null
    }
  }, [])

  const logout = useCallback(async () => {
    const t = session?.token
    writeStored(null)
    setSession(null)
    if (t) {
      fetch(`${BASE}/api/auth/logout`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${t}` },
      }).catch(() => {})
    }
  }, [session])

  const value = useMemo(
    () => ({
      session,
      user: session?.user ?? null,
      token: session?.token ?? null,
      isAuthenticated: !!session,
      ready,
      config,
      login,
      signup,
      logout,
      checkUsername,
    }),
    [session, ready, config, login, signup, logout, checkUsername]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}

/** Current bearer token, for the data API client. */
export function authToken() {
  return readStored()?.token ?? null
}
