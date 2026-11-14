import { afterEach, beforeEach, expect, test, vi } from "vitest"
import { POST } from "./route"

const fetcher = vi.fn()
const request = (body: unknown = { input: { departure_city: "pl-warsaw" } }) => new Request("http://localhost/api/round-trip", {
  method: "POST", body: JSON.stringify(body),
})
beforeEach(() => {
  vi.stubEnv("APP_ACCESS_TOKEN", "server-secret")
  vi.stubEnv("BACKEND_GRAPHQL_URL", "http://backend/graphql")
  vi.stubGlobal("fetch", fetcher)
  fetcher.mockReset()
})
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs() })

test("correlates browser and backend logs without logging search payloads or credentials", async () => {
  const info = vi.spyOn(console, "info").mockImplementation(() => {})
  try {
    const requestId = "a".repeat(32)
    fetcher.mockResolvedValue(Response.json({ data: { round_trip_options: [] } }, { headers: { "X-Request-ID": requestId } }))
    const response = await POST(request({ input: { departure_city: "private-search" } }))
    expect(response.headers.get("x-request-id")).toBe(requestId)
    const log = JSON.parse(info.mock.calls[0][0])
    expect(log).toMatchObject({ event: "search.upstream_response", backend_request_id: requestId, status: 200 })
    expect(JSON.stringify(info.mock.calls)).not.toMatch(/private-search|server-secret|http:\/\/backend/)
  } finally { info.mockRestore() }
})

test("does not forward an untrusted upstream request identifier", async () => {
  fetcher.mockResolvedValue(Response.json({}, { headers: { "X-Request-ID": "private-upstream-detail" } }))
  const response = await POST(request())
  expect(response.headers.has("x-request-id")).toBe(false)
})

test("authenticates upstream and sends a fixed schema query", async () => {
  fetcher.mockResolvedValue(Response.json({ data: { round_trip_options: [] } }))
  const response = await POST(request({ input: { departure_city: "pl-warsaw", min_cities: 3 } }))
  expect(response.status).toBe(200)
  expect(fetcher).toHaveBeenCalledWith("http://backend/graphql", expect.objectContaining({
    redirect: "error", cache: "no-store", headers: expect.objectContaining({ Authorization: "Bearer server-secret" }),
  }))
  const body = JSON.parse(fetcher.mock.calls[0][1].body)
  expect(body.operationName).toBe("RoundTripOptions")
  expect(body.variables.input.departure_city).toBe("pl-warsaw")
  expect(body.variables.input.min_cities).toBe(3)
  expect(await response.text()).not.toContain("server-secret")
})
test("fails closed without configured authentication", async () => {
  vi.stubEnv("APP_ACCESS_TOKEN", "")
  expect((await POST(request())).status).toBe(503)
  expect(fetcher).not.toHaveBeenCalled()
})
test.each([null, {}, { input: [] }, { input: null }])("rejects malformed inputs %j", async (body) => {
  expect((await POST(request(body))).status).toBe(400)
  expect(fetcher).not.toHaveBeenCalled()
})
test("sanitizes network and HTTP failures", async () => {
  fetcher.mockRejectedValueOnce(new Error("server-secret"))
  expect((await POST(request())).status).toBe(502)
  fetcher.mockResolvedValueOnce(new Response("private upstream details", { status: 401 }))
  const response = await POST(request())
  expect(response.status).toBe(502)
  expect(await response.text()).not.toContain("private")
})

test("bounds request body size", async () => {
  expect((await POST(request({ input: { departure_city: "x".repeat(65536) } }))).status).toBe(413)
  expect(fetcher).not.toHaveBeenCalled()
})

test("rejects cross-origin requests before provider access", async () => {
  const input = new Request("http://localhost/api/round-trip", { method: "POST", headers: { Origin: "https://untrusted.example" }, body: "{}" })
  expect((await POST(input)).status).toBe(403)
  expect(fetcher).not.toHaveBeenCalled()
})

test("accepts the same staging origin through HTTPS ingress", async () => {
  fetcher.mockResolvedValue(Response.json({ data: { round_trip_options: [] } }))
  const input = new Request("http://staging.example/api/round-trip", { method: "POST",
    headers: { Origin: "https://staging.example", "x-forwarded-proto": "https" }, body: JSON.stringify({ input: {} }) })
  expect((await POST(input)).status).toBe(200)
})

test("accepts browser requests through the published Docker host and port", async () => {
  fetcher.mockResolvedValue(Response.json({ data: { round_trip_options: [] } }))
  const input = new Request("http://0.0.0.0:3000/api/round-trip", { method: "POST",
    headers: { Origin: "http://localhost:3100", Host: "localhost:3100" }, body: JSON.stringify({ input: {} }) })
  expect((await POST(input)).status).toBe(200)
})
