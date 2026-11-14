import { ROUND_TRIP_QUERY } from "@/lib/round-trip-search"

export async function POST(request: Request): Promise<Response> {
  const origin = request.headers.get("origin")
  const publicUrl = new URL(request.url)
  const forwardedHost = request.headers.get("x-forwarded-host") || request.headers.get("host")
  if (forwardedHost) publicUrl.host = forwardedHost
  const forwardedProtocol = request.headers.get("x-forwarded-proto")
  if (forwardedProtocol === "https" || forwardedProtocol === "http") publicUrl.protocol = `${forwardedProtocol}:`
  if (origin && origin !== publicUrl.origin) {
    return Response.json({ error: "Cross-origin searches are not allowed." }, { status: 403 })
  }
  const token = process.env.APP_ACCESS_TOKEN
  const url = process.env.BACKEND_GRAPHQL_URL
  if (!token?.trim() || !url) return Response.json({ error: "Trip search is not configured." }, { status: 503 })
  let payload: unknown
  try {
    const reader = request.body?.getReader()
    if (!reader) throw new Error("Missing body")
    const chunks: Uint8Array[] = []
    let size = 0
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      size += value.byteLength
      if (size > 65536) {
        await reader.cancel()
        return Response.json({ error: "Search request is too large." }, { status: 413 })
      }
      chunks.push(value)
    }
    payload = JSON.parse(Buffer.concat(chunks).toString("utf8"))
  } catch {
    return Response.json({ error: "Invalid search request." }, { status: 400 })
  }
  if (!payload || typeof payload !== "object" || !("input" in payload) ||
      !payload.input || typeof payload.input !== "object" || Array.isArray(payload.input)) {
    return Response.json({ error: "Supply round-trip search input." }, { status: 400 })
  }
  const started = Date.now()
  let backendRequestId: string | undefined
  try {
    const upstream = await fetch(url, {
      method: "POST", redirect: "error", cache: "no-store",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ query: ROUND_TRIP_QUERY, operationName: "RoundTripOptions", variables: { input: payload.input } }),
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(240000)]),
    })
    const requestId = upstream.headers.get("x-request-id")
    if (requestId && /^[a-f0-9]{32}$/.test(requestId)) backendRequestId = requestId
    console.info(JSON.stringify({ event: "search.upstream_response", backend_request_id: backendRequestId,
      status: upstream.status, duration_ms: Date.now() - started }))
    if (!upstream.ok) throw new Error("Upstream failure")
    return Response.json(await upstream.json(), { headers: { "Cache-Control": "no-store",
      ...(backendRequestId ? { "X-Request-ID": backendRequestId } : {}) } })
  } catch {
    console.warn(JSON.stringify({ event: "search.upstream_failed", backend_request_id: backendRequestId,
      duration_ms: Date.now() - started }))
    return Response.json({ error: "Trip search is unavailable. Please try again later." }, { status: 502,
      headers: backendRequestId ? { "X-Request-ID": backendRequestId } : {} })
  }
}
