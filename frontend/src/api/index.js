// Toutes les requêtes passent par le backend Railway via VITE_API_URL

export const API_BASE = import.meta.env.VITE_API_URL || ''

// ── Generic POST (JSON in, JSON out) ─────────────────────────────────────────
export async function post(path, body) {
  const res = await fetch(API_BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = res.statusText
    try { const j = await res.json(); detail = JSON.stringify(j) } catch {}
    throw new Error('HTTP ' + res.status + ': ' + detail)
  }
  return res.json()
}

// ── Generic DELETE ────────────────────────────────────────────────────────────
export async function del(path) {
  const res = await fetch(API_BASE + path, { method: 'DELETE' })
  if (!res.ok) {
    let detail = res.statusText
    try { const j = await res.json(); detail = JSON.stringify(j) } catch {}
    throw new Error('HTTP ' + res.status + ': ' + detail)
  }
  return res.json()
}

// ── SSE streaming POST ────────────────────────────────────────────────────────
export async function streamPost(path, body, handlers = {}) {
  const url = API_BASE + path
  console.log('[API] POST', url, JSON.stringify(body))

  let res
  try {
    res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch (err) {
    console.error('[API] Network error', err)
    handlers.onError?.({ message: 'Network error: ' + err.message })
    handlers.onDone?.()
    return
  }

  if (!res.ok) {
    let detail = res.statusText
    try { const j = await res.json(); detail = JSON.stringify(j) } catch {}
    console.error('[API] HTTP', res.status, detail)
    handlers.onError?.({ message: 'HTTP ' + res.status + ': ' + detail })
    handlers.onDone?.()
    return
  }

  const reader  = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop()
      for (const part of parts) {
        for (const line of part.split('\n')) {
          if (!line.startsWith('data:')) continue
          const raw = line.slice(5).trim()
          if (!raw || raw === '[DONE]') continue
          let evt
          try { evt = JSON.parse(raw) } catch { continue }
          console.log('[SSE]', evt.type, evt)
          dispatch(evt, handlers)
        }
      }
    }
  } catch (err) {
    console.error('[SSE] read error', err)
    handlers.onError?.({ message: 'Stream error: ' + err.message })
  }

  handlers.onDone?.()
}

function dispatch(evt, h) {
  switch (evt.type) {
    case 'progress': h.onProgress?.(evt);      break
    case 'papers':   h.onPapers?.(evt.data);   break
    case 'analysis': h.onAnalysis?.(evt);      break
    case 'verdict':  h.onVerdict?.(evt.data);  break
    case 'review':   h.onReview?.(evt.data);   break
    case 'sources':  h.onSources?.(evt.data);  break
    case 'token':    h.onToken?.(evt);         break
    case 'warning':  h.onWarning?.(evt);       break  // low relevance disclaimer
    case 'done':     h.onDone?.();             break
    case 'error':    h.onError?.(evt);         break
  }
}

// ── Legacy helper kept for PaperSummarizer compatibility ─────────────────────
export async function summarizePaper(paper) {
  const res = await fetch(API_BASE + '/api/summarize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paper }),
  })
  if (!res.ok) throw new Error('HTTP ' + res.status)
  return (await res.json()).summary
}
