const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

/**
 * Streams an SSE endpoint and calls callbacks for each event type.
 * @param {string} path
 * @param {object} body
 * @param {object} handlers  { onProgress, onPapers, onAnalysis, onVerdict, onReview, onDone, onError }
 */
export async function streamPost(path, body, handlers = {}) {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    handlers.onError?.({ message: `HTTP ${res.status}` })
    handlers.onDone?.()
    return
  }
  const reader  = res.body.getReader()
  const decoder = new TextDecoder()
  let   buffer  = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop()
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      try {
        const event = JSON.parse(line.slice(6))
        const t = event.type
        if      (t === 'progress') handlers.onProgress?.(event)
        else if (t === 'papers')   handlers.onPapers?.(event.data)
        else if (t === 'analysis') handlers.onAnalysis?.(event)
        else if (t === 'verdict')  handlers.onVerdict?.(event.data)
        else if (t === 'review')   handlers.onReview?.(event.data)
        else if (t === 'done')     handlers.onDone?.()
        else if (t === 'error')    handlers.onError?.(event)
      } catch {}
    }
  }
  handlers.onDone?.()
}

export async function summarizePaper(paper) {
  const res = await fetch(`${BASE}/api/summarize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paper }),
  })
  const data = await res.json()
  return data.summary
}

export async function clearCache() {
  return fetch(`${BASE}/api/cache`, { method: 'DELETE' })
}

export async function getHealth() {
  const res = await fetch(`${BASE}/api/health`)
  return res.json()
}
