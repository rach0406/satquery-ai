import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../lib/auth.jsx'
import { Icon } from '../components/Icons'
import { Logo, OrbitVisual, Starfield, Wordmark } from '../components/Brand'

const HIGHLIGHTS = [
  ['Real satellite imagery', 'MODIS, VIIRS and Sentinel-1 SAR from NASA GIBS — no credentials needed.'],
  ['Ten specialist tools', 'An agentic controller routes each question to the right models.'],
  ['Every number traced', 'Measurements only. Untraceable figures are rejected before you see them.'],
]

export default function Auth() {
  const navigate = useNavigate()
  const location = useLocation()
  const { login, signup, isAuthenticated, config, ready, checkUsername } = useAuth()

  const initialMode = new URLSearchParams(location.search).get('mode') === 'signup'
  const [isSignup, setIsSignup] = useState(initialMode)
  const [form, setForm] = useState({
    username: '',
    password: '',
    display_name: '',
    email: '',
    organisation: '',
  })
  const [showPw, setShowPw] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  //: Result of the availability check: null, or {available, reason}.
  const [nameCheck, setNameCheck] = useState(null)

  const from = location.state?.from?.pathname || '/app'

  useEffect(() => {
    if (ready && isAuthenticated) navigate(from, { replace: true })
  }, [ready, isAuthenticated, navigate, from])

  const set = (k) => (e) => {
    if (k === 'username') setNameCheck(null)
    setForm((f) => ({ ...f, [k]: e.target.value }))
  }

  /* Catch the obvious problems here so the user is told immediately rather
     than after a round trip. The server re-checks all of it — this is a
     courtesy, not the enforcement point. */
  function localProblem() {
    const u = form.username.trim()
    if (!u) return isSignup ? 'Choose a username.' : 'Enter your username or email.'
    if (!form.password) return 'Enter your password.'
    if (!isSignup) return null
    if (u.length < 3) return 'Username must be at least 3 characters long.'
    if (!/^[a-zA-Z0-9._-]+$/.test(u))
      return 'Username may only contain letters, digits, dot, underscore or hyphen.'
    if (form.password.length < 8) return 'Password must be at least 8 characters long.'
    if (!/[A-Za-z]/.test(form.password)) return 'Password must contain at least one letter.'
    if (!/\d/.test(form.password)) return 'Password must contain at least one number.'
    if (form.email.trim() && !/^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$/.test(form.email.trim()))
      return 'That email address does not look valid.'
    return null
  }

  async function submit(e) {
    e.preventDefault()
    if (busy) return
    const problem = localProblem()
    if (problem) {
      setError(problem)
      return
    }
    setBusy(true)
    setError(null)
    try {
      if (isSignup) {
        await signup({
          username: form.username.trim(),
          password: form.password,
          display_name: form.display_name.trim() || undefined,
          email: form.email.trim() || undefined,
          organisation: form.organisation.trim() || undefined,
        })
      } else {
        await login(form.username.trim(), form.password)
      }
      navigate(from, { replace: true })
    } catch (err) {
      setError(err.message || 'Something went wrong. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  function fillDemo() {
    const d = config?.demo_account
    if (!d) return
    setIsSignup(false)
    setError(null)
    setForm((f) => ({ ...f, username: d.username, password: d.password }))
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      {/* ------------------------------------------------ brand panel */}
      <aside className="relative hidden overflow-hidden bg-night-sky lg:block">
        <Starfield />
        <div className="absolute inset-0 night-grid opacity-50" />

        <div className="relative flex h-full flex-col justify-between p-12 xl:p-16">
          <Wordmark to="/" tone="dark" />

          <div className="py-10">
            <OrbitVisual className="mx-auto w-full max-w-[330px] opacity-95" />
          </div>

          <div>
            <h2 className="max-w-md text-h2 leading-tight text-white">
              Satellite intelligence, in plain language.
            </h2>
            <ul className="mt-9 space-y-5">
              {HIGHLIGHTS.map(([t, d]) => (
                <li key={t} className="flex gap-3.5">
                  <span className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-orbit-500/25 text-orbit-300">
                    <Icon.check size={13} />
                  </span>
                  <span>
                    <span className="block text-small font-semibold text-white">{t}</span>
                    <span className="mt-0.5 block text-small leading-relaxed text-paper-300/65">
                      {d}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-10 border-t border-white/10 pt-6 text-tiny text-paper-300/50">
              SIH26167 · ISRO / Department of Space · Team Avengers
            </p>
          </div>
        </div>
      </aside>

      {/* ------------------------------------------------ form panel */}
      <main className="flex flex-col bg-paper-100 bg-paper-wash">
        <div className="flex items-center justify-between p-6 lg:hidden">
          <Wordmark to="/" />
        </div>

        <div className="flex flex-1 items-center justify-center px-6 py-10 lg:px-12">
          <div className="w-full max-w-md animate-floatUp">
            <Link
              to="/"
              className="mb-8 inline-flex items-center gap-1.5 text-small font-medium text-ink-400 transition-colors hover:text-ink-700"
            >
              <span className="rotate-180">
                <Icon.chevron size={14} />
              </span>
              Back to home
            </Link>

            <div className="hidden lg:block">
              <Logo size={40} />
            </div>

            <h1 className="mt-6 text-h2">{isSignup ? 'Create your account' : 'Welcome back'}</h1>
            <p className="mt-2.5 text-base text-ink-500">
              {isSignup
                ? 'Set up access to the SatQuery AI analysis console.'
                : 'Sign in to open the analysis console.'}
            </p>

            {/* demo credentials */}
            {config?.demo_account && (
              <div className="mt-7 rounded-card border border-orbit-200 bg-orbit-50 p-4">
                <div className="flex items-start gap-3">
                  <Icon.spark size={17} className="mt-0.5 shrink-0 text-orbit-600" />
                  <div className="min-w-0 flex-1">
                    <p className="text-small font-semibold text-orbit-800">
                      Demo account ready
                    </p>
                    <p className="mono mt-1.5 text-ink-500">
                      {config.demo_account.username} · {config.demo_account.password}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={fillDemo}
                    className="btn-secondary shrink-0 !px-3 !py-1.5 !text-tiny"
                  >
                    Use it
                  </button>
                </div>
              </div>
            )}

            <form onSubmit={submit} className="mt-7 space-y-5" noValidate>
              <div>
                <label className="field-label" htmlFor="username">
                  {isSignup ? 'Username' : 'Username or email'}
                </label>
                <input
                  id="username"
                  className="field"
                  value={form.username}
                  onChange={set('username')}
                  autoComplete="username"
                  autoCapitalize="none"
                  spellCheck="false"
                  placeholder={isSignup ? 'choose a username' : 'your username or email'}
                  onBlur={async () => {
                    if (!isSignup) return
                    const u = form.username.trim()
                    if (!u) return setNameCheck(null)
                    setNameCheck(await checkUsername(u))
                  }}
                  required
                />
                {isSignup && (
                  <p
                    className={`mt-2 text-tiny ${
                      nameCheck && !nameCheck.available
                        ? 'text-signal-red'
                        : nameCheck?.available
                          ? 'text-signal-green'
                          : 'text-ink-400'
                    }`}
                  >
                    {nameCheck
                      ? nameCheck.available
                        ? `“${form.username.trim()}” is available.`
                        : nameCheck.reason
                      : '3–32 characters: letters, digits, dot, underscore or hyphen.'}
                  </p>
                )}
              </div>

              {isSignup && (
                <>
                  <div>
                    <label className="field-label" htmlFor="display_name">
                      Full name <span className="font-normal text-ink-300">optional</span>
                    </label>
                    <input
                      id="display_name"
                      className="field"
                      value={form.display_name}
                      onChange={set('display_name')}
                      autoComplete="name"
                      placeholder="Your name"
                    />
                  </div>
                  <div className="grid gap-5 sm:grid-cols-2">
                    <div>
                      <label className="field-label" htmlFor="email">
                        Email <span className="font-normal text-ink-300">optional</span>
                      </label>
                      <input
                        id="email"
                        type="email"
                        className="field"
                        value={form.email}
                        onChange={set('email')}
                        autoComplete="email"
                        placeholder="you@org.in"
                      />
                    </div>
                    <div>
                      <label className="field-label" htmlFor="organisation">
                        Organisation <span className="font-normal text-ink-300">optional</span>
                      </label>
                      <input
                        id="organisation"
                        className="field"
                        value={form.organisation}
                        onChange={set('organisation')}
                        autoComplete="organization"
                        placeholder="Institute or agency"
                      />
                    </div>
                  </div>
                </>
              )}

              <div>
                <label className="field-label" htmlFor="password">
                  Password
                </label>
                <div className="relative">
                  <input
                    id="password"
                    type={showPw ? 'text' : 'password'}
                    className="field pr-12"
                    value={form.password}
                    onChange={set('password')}
                    autoComplete={isSignup ? 'new-password' : 'current-password'}
                    placeholder={isSignup ? 'at least 8 characters' : '••••••••'}
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPw((v) => !v)}
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-md p-2 text-ink-300 transition-colors hover:bg-paper-200 hover:text-ink-600"
                    aria-label={showPw ? 'Hide password' : 'Show password'}
                  >
                    <Icon.eye size={17} />
                  </button>
                </div>
                {isSignup && (
                  <p className="mt-2 text-tiny text-ink-400">
                    {config?.password_policy ||
                      'At least 8 characters, including a letter and a number.'}
                  </p>
                )}
              </div>

              {error && (
                <div
                  role="alert"
                  className="flex items-start gap-2.5 rounded-card border border-signal-red/30 bg-signal-red/8 px-4 py-3"
                >
                  <Icon.alert size={16} className="mt-0.5 shrink-0 text-signal-red" />
                  <p className="text-small leading-relaxed text-signal-red">{error}</p>
                </div>
              )}

              <button type="submit" className="btn-primary btn-lg w-full" disabled={busy}>
                {busy ? (
                  <>
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                    {isSignup ? 'Creating account…' : 'Signing in…'}
                  </>
                ) : (
                  <>
                    {isSignup ? 'Create account' : 'Sign in'}
                    <Icon.chevron size={15} />
                  </>
                )}
              </button>
            </form>

            <p className="mt-7 text-center text-small text-ink-500">
              {isSignup ? 'Already have an account?' : 'New to SatQuery AI?'}{' '}
              <button
                type="button"
                onClick={() => {
                  setIsSignup((v) => !v)
                  setError(null)
                }}
                className="rounded font-semibold text-orbit-600 transition-colors hover:text-orbit-700"
              >
                {isSignup ? 'Sign in instead' : 'Create an account'}
              </button>
            </p>

            <p className="mt-8 border-t border-paper-300 pt-6 text-tiny leading-relaxed text-ink-400">
              Passwords are stored as salted PBKDF2-HMAC-SHA256 derivations and never in plain
              text. Sessions are signed tokens that expire on their own.
            </p>
          </div>
        </div>
      </main>
    </div>
  )
}
