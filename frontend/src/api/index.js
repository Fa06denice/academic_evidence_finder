const BASE = import.meta.env.VITE_API_URL || ''

export async function streamPost(path, body, handlers = {}) {
  const url = BASE + path
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

  const reader = res.body.getReader()
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
    case 'progress':  h.onProgress?.(evt); break
    case 'papers':    h.onPapers?.(evt.data); break
    case 'analysis':  h.onAnalysis?.(evt); break
    case 'verdict':   h.onVerdict?.(evt.data); break
    case 'review':    h.onReview?.(evt.data); break
    case 'error':     h.onError?.(evt); break
  }
}

export async function summarizePaper(paper) {
  const res = await fetch(BASE + '/api/summarize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paper }),
  })
  if (!res.ok) throw new Error('HTTP ' + res.status)
  return (await res.json()).summary
}
