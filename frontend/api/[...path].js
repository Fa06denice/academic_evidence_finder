// api/[...path].js  — Vercel serverless proxy
export const config = { runtime: 'edge' }

export default async function handler(req) {
  const url = new URL(req.url)
  const upstream = process.env.VITE_API_URL || process.env.API_URL || ''
  const target = upstream + url.pathname.replace(/^\/api/, '') + url.search

  const init = {
    method: req.method,
    headers: { 'Content-Type': 'application/json' },
  }
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    init.body = req.body
  }

  const res = await fetch(target, init)
  return new Response(res.body, {
    status: res.status,
    headers: {
      'Content-Type': res.headers.get('Content-Type') || 'application/json',
      'Cache-Control': 'no-cache',
      'X-Accel-Buffering': 'no',
      'Access-Control-Allow-Origin': '*',
    },
  })
}
