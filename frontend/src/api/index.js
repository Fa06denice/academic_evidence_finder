const BASE = import.meta.env.VITE_API_URL || ''

/**
 * streamPost — consomme un SSE stream FastAPI
 * Le backend envoie: data: {"type":"xxx", ...}


 */
export async function streamPost(path, body, handlers = {}) {
  const url = BASE + path
  console.log('[API] POST', url, body)

  let res
  try {
    res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body),
    })
  } catch (err) {
    console.error('[API] fetch error', err)
    handlers.onError?.({ message: err.message })
    handlers.onDone?.()
    return
  }

  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    console.error('[API] HTTP error', res.status, text)
    handlers.onError?.({ message: `HTTP ${res.status}: ${text}` })
    handlers.onDone?.()
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // Chaque event SSE est séparé par \n\n
    const parts = buffer.split('\n\n')
    buffer = parts.pop() // garder le fragment incomplet

    for (const part of parts) {
      for (const line of part.split('\n')) {
        if (!line.startsWith('data:')) continue
        const raw = line.slice(5).trim()
        if (!raw || raw === '[DONE]') continue

        let evt
        try { evt = JSON.parse(raw) }
        catch (e) { console.warn('[API] JSON parse error', raw); continue }

        console.log('[SSE]', evt.type, evt)
        dispatch(evt, handlers)
      }
    }
  }

  handlers.onDone?.()
}

function dispatch(evt, h) {
  switch (evt.type) {
    case 'progress':  h.onProgress?.(evt); break
    case 'papers':    h.onPapers?.(evt.data); break
    case 'analysis':  h.onAnalysis?.(evt); break
    case 'verdict':   h.onVerdict?.(evt.data); break
    case 'review':    h.onReview?.(evt.data); break
    case 'error':     h.onError?.(evt); break
    case 'done':      /* géré par le while loop */ break
    default:          console.log('[SSE] unknown type:', evt.type)
  }
}

/** Résume un paper (non-streaming) */
export async function summarizePaper(paper) {
  const res = await fetch(BASE + '/api/summarize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paper }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = await res.json()
  return json.summary
}
