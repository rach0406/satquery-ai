import { authToken } from './auth.jsx'

const BASE = import.meta.env.VITE_API_BASE || ''

/* Attach the session token when there is one. The API accepts anonymous
   calls by default (so curl demos and /docs keep working) but records the
   caller when a token is present, and can be switched to hard-require it
   with SATQUERY_REQUIRE_AUTH. */
function authHeaders(extra = {}) {
  const t = authToken()
  return t ? { ...extra, Authorization: `Bearer ${t}` } : { ...extra }
}

async function jget(path) {
  const r = await fetch(`${BASE}${path}`, { headers: authHeaders() })
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} on ${path}`)
  return r.json()
}

async function jpost(path, body) {
  const r = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body),
  })
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`
    try {
      const j = await r.json()
      if (j.detail) detail = j.detail
    } catch {
      /* body was not JSON */
    }
    throw new Error(detail)
  }
  return r.json()
}

export const api = {
  health: () => jget('/api/health'),
  catalog: () => jget('/api/catalog'),
  registry: () => jget('/api/registry'),
  model: () => jget('/api/model'),
  samples: () => jget('/api/samples'),
  scenes: () => jget('/api/scenes'),
  locate: (q) => jget(`/api/locate?q=${encodeURIComponent(q)}`),
  parse: (query) => jpost('/api/parse', { query }),
  query: (body) => jpost('/api/query', body),
  saveReport: (body) => jpost('/api/report', body),

  async upload(file) {
    const fd = new FormData()
    fd.append('file', file)
    const r = await fetch(`${BASE}/api/scenes/upload`, {
      method: 'POST',
      body: fd,
      headers: authHeaders(),
    })
    if (!r.ok) {
      let detail = `${r.status} ${r.statusText}`
      try {
        const j = await r.json()
        if (j.detail) detail = j.detail
      } catch {
        /* body was not JSON */
      }
      throw new Error(detail)
    }
    return r.json()
  },
}

/**
 * Stream a query, calling `onEvent` for each pipeline stage.
 *
 * Falls back to the non-streaming endpoint if SSE is unavailable, so the demo
 * still works behind a proxy that buffers responses.
 */
export async function streamQuery(body, onEvent, signal) {
  let response
  try {
    response = await fetch(`${BASE}/api/query/stream`, {
      method: 'POST',
      headers: authHeaders({
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      }),
      body: JSON.stringify(body),
      signal,
    })
  } catch (err) {
    if (err.name === 'AbortError') throw err
    onEvent({ event: 'notice', message: 'Streaming unavailable — using the direct endpoint.' })
    return { result: await api.query(body) }
  }

  if (!response.ok || !response.body) {
    onEvent({ event: 'notice', message: 'Streaming unavailable — using the direct endpoint.' })
    return { result: await api.query(body) }
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result = null

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() ?? ''
    for (const part of parts) {
      const line = part.split('\n').find((l) => l.startsWith('data: '))
      if (!line) continue
      let msg
      try {
        msg = JSON.parse(line.slice(6))
      } catch {
        continue
      }
      if (msg.event === 'result') result = msg.result
      onEvent(msg)
    }
  }
  return { result }
}
