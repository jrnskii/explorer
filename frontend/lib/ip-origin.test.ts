import assert from "node:assert/strict"
import { afterEach, test, vi } from "vitest"

import { detectDepartureCity, lookupIpOrigin } from "./ip-origin"

function stubFetch(body: unknown, ok = true) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok, json: async () => body }))
  )
}

afterEach(() => vi.unstubAllGlobals())

test("returns the country code and capital on success", async () => {
  stubFetch({ success: true, country_code: "LT", capital: "Vilnius" })
  assert.deepEqual(await lookupIpOrigin(), { countryCode: "LT", capital: "Vilnius" })
})

test("returns null for failed, malformed or incomplete responses", async () => {
  stubFetch({ success: false, message: "Invalid IP" })
  assert.equal(await lookupIpOrigin(), null)
  stubFetch({ success: true, country_code: "LT" })
  assert.equal(await lookupIpOrigin(), null)
  stubFetch({ success: true, country_code: "LT", capital: "  " })
  assert.equal(await lookupIpOrigin(), null)
  stubFetch(null)
  assert.equal(await lookupIpOrigin(), null)
  stubFetch({}, false)
  assert.equal(await lookupIpOrigin(), null)
})

test("returns null when the request fails", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new Error("offline"))))
  assert.equal(await lookupIpOrigin(), null)
})

test("resolves the capital of the IP country to a city", async () => {
  stubFetch({ success: true, country_code: "LT", capital: "Vilnius" })
  const city = await detectDepartureCity()
  assert.equal(city?.name, "Vilnius")
  assert.equal(city?.country, "Lithuania")
})

test("does not confuse same-named cities in other countries", async () => {
  stubFetch({ success: true, country_code: "FR", capital: "Vilnius" })
  assert.equal(await detectDepartureCity(), null)
})

test("returns null for capitals outside the dataset", async () => {
  stubFetch({ success: true, country_code: "JP", capital: "Tokyo" })
  assert.equal(await detectDepartureCity(), null)
})
