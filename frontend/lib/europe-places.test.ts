import assert from "node:assert/strict"
import { test } from "vitest"

import { EU_CAPITALS } from "./eu-capitals"
import { resolvePlaces } from "./europe-places"

test("no departure starts at the central capital without an origin", () => {
  const r = resolvePlaces(null)
  assert.equal(r.origin, null)
  assert.equal(r.places.length, EU_CAPITALS.length)
  assert.equal(r.places[r.start].name, "Prague")
})

test("a capital departure is matched by name, ignoring case and spaces", () => {
  const r = resolvePlaces({ name: "  pArIs " })
  assert.equal(r.places[r.start].name, "Paris")
  assert.equal(r.origin, r.start)
  assert.equal(r.places.length, EU_CAPITALS.length)
})

test("a non-capital departure inside the map is added as an extra point", () => {
  const r = resolvePlaces({ name: "Barcelona", lon: 2.1686, lat: 41.3874 })
  assert.equal(r.places.length, EU_CAPITALS.length + 1)
  assert.equal(r.origin, EU_CAPITALS.length)
  assert.equal(r.start, r.origin)
  assert.deepEqual(r.places[r.start], { name: "Barcelona", lon: 2.1686, lat: 41.3874 })
})

test("a non-capital without coordinates cannot be shown", () => {
  const r = resolvePlaces({ name: "Barcelona" })
  assert.equal(r.origin, null)
  assert.equal(r.places.length, EU_CAPITALS.length)
})

test("a city far outside Europe is not added to the map", () => {
  const r = resolvePlaces({ name: "New York", lon: -74.006, lat: 40.7128 })
  assert.equal(r.origin, null)
  assert.equal(r.places.length, EU_CAPITALS.length)
})

test("non-finite coordinates are rejected", () => {
  const r = resolvePlaces({ name: "Nowhere", lon: Number.NaN, lat: 50 })
  assert.equal(r.origin, null)
})

test("a city on top of a capital under another name resolves to the capital", () => {
  const r = resolvePlaces({ name: "City of Brussels", lon: 4.35, lat: 50.85 })
  assert.equal(r.places.length, EU_CAPITALS.length)
  assert.equal(r.places[r.start].name, "Brussels")
  assert.equal(r.origin, r.start)
})

test("a city a short trip from a capital is still its own point", () => {
  const r = resolvePlaces({ name: "Antwerp", lon: 4.4, lat: 51.22 })
  assert.equal(r.places.length, EU_CAPITALS.length + 1)
})
