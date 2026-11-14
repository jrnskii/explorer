import { expect, test } from "vitest"

import { GET } from "./route"

async function call(headers: Record<string, string>) {
  const res = GET(new Request("http://localhost/api/geo", { headers }))
  return res.json()
}

test("derives country and currency from the edge geo header", async () => {
  expect(await call({ "x-vercel-ip-country": "PL" })).toEqual({
    country: "PL",
    currency: "PLN",
  })
  expect(await call({ "cf-ipcountry": "de" })).toEqual({
    country: "DE",
    currency: "EUR",
  })
})

test("returns a country without currency when unsupported", async () => {
  expect(await call({ "x-vercel-ip-country": "JP" })).toEqual({
    country: "JP",
    currency: null,
  })
})

test("returns nulls without a usable header", async () => {
  expect(await call({})).toEqual({ country: null, currency: null })
  expect(await call({ "cf-ipcountry": "XX" })).toEqual({
    country: null,
    currency: null,
  })
})
