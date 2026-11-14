import { expect, test } from "bun:test"
import { POST } from "@/app/api/pricing/route"

const request = (body: string) => new Request("http://localhost/api/pricing", { method: "POST", body })
test("pricing endpoint rejects malformed and oversized batches before starting a backend", async () => {
  for (const body of ["{", "null", "{}", '{"queries":[]}', JSON.stringify({ queries: Array(65).fill({}) })]) {
    expect((await POST(request(body))).status).toBe(400)
  }
  expect((await POST(request("a".repeat(65537)))).status).toBe(413)
})
test("pricing endpoint validates mode, dates, labels and traveler counts", async () => {
  const query = { mode: "PLANES", origin: "Paris", destination: "Rome", departure_date: "2030-12-01", travelers: 1 }
  for (const change of [{ mode: "INVALID" }, { origin: "" }, { departure_date: "2030-02-30" }, { travelers: 0 }, { travelers: 1.5 }]) {
    expect((await POST(request(JSON.stringify({ queries: [{ ...query, ...change }] })))).status).toBe(400)
  }
})
