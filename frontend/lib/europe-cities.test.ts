import assert from "node:assert/strict"
import { test } from "vitest"

import { fold, popularEuropeCities, searchEuropeCities } from "./europe-cities"

test("fold ignores case and diacritics", () => {
  assert.equal(fold("  München "), "munchen")
  assert.equal(fold("Łódź"), "lodz")
  assert.equal(fold("Kraków"), "krakow")
})

test("empty or blank queries return nothing", async () => {
  assert.deepEqual(await searchEuropeCities(""), [])
  assert.deepEqual(await searchEuropeCities("   "), [])
  assert.deepEqual(await searchEuropeCities("Paris", 0), [])
})

test("finds cities beyond the capitals, with country and coordinates", async () => {
  const [first] = await searchEuropeCities("barcelona")
  assert.equal(first.name, "Barcelona")
  assert.equal(first.country, "Spain")
  assert.ok(first.lat !== undefined && Math.abs(first.lat - 41.39) < 0.2)
  assert.ok(first.lon !== undefined && Math.abs(first.lon - 2.17) < 0.2)
})

test("matches without diacritics", async () => {
  const names = (await searchEuropeCities("zurich")).map((c) => c.name)
  assert.ok(names.includes("Zürich"), names.join(", "))
})

test("prefix matches rank before substring matches and respect the limit", async () => {
  const r = await searchEuropeCities("ber", 5)
  assert.ok(r.length <= 5)
  assert.ok(r.every((c) => c.name.toLowerCase().includes("ber")))
  assert.ok(fold(r[0].name).startsWith("ber"))
})

test("unknown queries return an empty list", async () => {
  assert.deepEqual(await searchEuropeCities("zzzzqqqq"), [])
})

test("ids are unique and results are plain European cities", async () => {
  const all = await searchEuropeCities("a", 500)
  assert.equal(new Set(all.map((c) => c.id)).size, all.length)
  assert.ok(!all.some((c) => c.name === "Tokyo" || c.name === "New York"))
})

test("popular cities come first by population", async () => {
  const top = await popularEuropeCities(3)
  assert.equal(top.length, 3)
  assert.equal(top[0].name, "Istanbul")
})
