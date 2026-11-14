import assert from "node:assert/strict"
import { describe, test } from "vitest"

import { EU_CAPITALS } from "./eu-capitals"
import {
  CASCADE_BRANCHING,
  HOLD_MS,
  ROUTE_COUNT,
  ROUTE_FADE_MS,
  STAGGER_MS,
  TRAIL,
  arcPath,
  pickDestinations,
  planCascade,
  planRound,
  roundDurationMs,
  type LonLat,
} from "./europe-route-wave"

const points = EU_CAPITALS.map((c): LonLat => [c.lon, c.lat])
const madrid = EU_CAPITALS.findIndex((c) => c.name === "Madrid")

describe("pickDestinations", () => {
  test("returns the requested number of distinct destinations, never the origin", () => {
    const picked = pickDestinations(points, madrid)
    assert.equal(picked.length, ROUTE_COUNT)
    assert.equal(new Set(picked).size, ROUTE_COUNT)
    assert.ok(!picked.includes(madrid))
  })

  test("is deterministic and varies with the phase", () => {
    assert.deepEqual(pickDestinations(points, madrid, 7, 0), pickDestinations(points, madrid, 7, 0))
    assert.notDeepEqual(pickDestinations(points, madrid, 7, 0), pickDestinations(points, madrid, 7, 1))
  })

  test("handles too few points and non-positive counts", () => {
    assert.deepEqual(pickDestinations([[0, 0]], 0), [])
    assert.deepEqual(pickDestinations(points, madrid, 0), [])
    assert.deepEqual(pickDestinations(points, 999), [])
    assert.equal(pickDestinations(points.slice(0, 3), 0).length <= 2, true)
  })

  test("skips places too close to the origin", () => {
    const near: LonLat[] = [
      [0, 0],
      [0.01, 0.01],
    ]
    assert.deepEqual(pickDestinations(near, 0), [])
  })
})

describe("planRound", () => {
  const routes = planRound(points[madrid], pickDestinations(points, madrid).map((i) => points[i]))

  test("staggers starts so that routes overlap", () => {
    routes.forEach((r, i) => assert.equal(r.startMs, i * STAGGER_MS))
    assert.ok(routes[0].beamMs > STAGGER_MS)
    // Starts are spread over roughly 1-1.5 seconds.
    const span = routes[routes.length - 1].startMs
    assert.ok(span >= 750 && span <= 1500, `span ${span}`)
  })

  test("the beam head reaches the destination before its trail has left", () => {
    for (const r of routes) {
      assert.ok(Math.abs(r.drawMs * (1 + TRAIL) - r.beamMs) < 1e-6)
      assert.ok(r.drawMs < r.beamMs)
    }
  })

  test("round lasts until the last route has faded", () => {
    const last = routes[routes.length - 1]
    assert.equal(roundDurationMs(routes), last.startMs + last.beamMs + HOLD_MS + ROUTE_FADE_MS)
    assert.equal(roundDurationMs([]), 0)
  })

  test("handles no destinations", () => {
    assert.deepEqual(planRound(points[madrid], []), [])
  })
})

describe("arcPath", () => {
  const parse = (d: string) => d.match(/-?\d+(\.\d+)?/g)!.map(Number)

  test("is a quadratic curve through both endpoints", () => {
    const [x0, y0, cx, cy, x1, y1] = parse(arcPath([0, 100], [200, 100]))
    assert.deepEqual([x0, y0, x1, y1], [0, 100, 200, 100])
    assert.equal(cx, 100)
    assert.ok(cy < 100, "arc bows upwards")
  })

  test("bows upwards in both directions", () => {
    assert.ok(parse(arcPath([200, 100], [0, 100]))[3] < 100)
    assert.ok(parse(arcPath([0, 0], [100, 100]))[3] < 50)
    assert.ok(parse(arcPath([100, 100], [0, 0]))[3] < 50)
  })

  test("a zero-length route stays finite", () => {
    const nums = parse(arcPath([5, 5], [5, 5]))
    assert.ok(nums.every(Number.isFinite))
  })
})

describe("planCascade", () => {
  const routes = planCascade(points, madrid)
  const key = (p: LonLat) => `${p[0]},${p[1]}`

  test("fans out from the origin, then continues from arrival cities", () => {
    const [first, second, third] = CASCADE_BRANCHING
    assert.ok(routes.filter((r) => r.key.startsWith("0:")).length <= first)
    assert.ok(routes.length > first)
    assert.ok(routes.length <= first + first * second + first * second * third)
  })

  test("every non-root route leaves a city an earlier beam arrives at, after it arrives", () => {
    for (const r of routes.filter((x) => !x.key.startsWith("0:"))) {
      const parent = routes.find((p) => key(p.to) === key(r.from) && p.startMs + p.drawMs <= r.startMs)
      assert.ok(parent, `no parent for ${r.key}`)
    }
  })

  test("never doubles back to a city on its own path", () => {
    for (const r of routes) assert.notEqual(key(r.from), key(r.to))
  })

  test("is deterministic", () => {
    assert.deepEqual(planCascade(points, madrid), routes)
  })

  test("keys are unique and an empty branching plan yields no routes", () => {
    assert.equal(new Set(routes.map((r) => r.key)).size, routes.length)
    assert.deepEqual(planCascade(points, madrid, 0, []), [])
  })
})
