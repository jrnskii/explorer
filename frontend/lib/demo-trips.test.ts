import { describe, expect, test } from "vitest"

import { DEMO_BEST_OPTION, DEMO_OPTIONS, DEMO_STOP_NAMES, DEMO_STOP_POINTS } from "./demo-trips"

describe("demo trips", () => {
  test("the showcased trip is Vilnius-Warsaw-Berlin-Stockholm-Riga-Vilnius", () => {
    expect(DEMO_STOP_NAMES).toEqual(["Vilnius", "Warsaw", "Berlin", "Stockholm", "Riga", "Vilnius"])
    expect(DEMO_STOP_POINTS).toHaveLength(DEMO_STOP_NAMES.length)
    expect(DEMO_BEST_OPTION.path.map((l) => l.transport_type)).toEqual([
      "TRAINS", "PLANES", "PLANES", "PLANES", "BUSSES",
    ])
  })

  test("the best option is listed first and is the cheapest", () => {
    expect(DEMO_OPTIONS[0]).toBe(DEMO_BEST_OPTION)
    const prices = DEMO_OPTIONS.map((o) => Number(o.total_price.amount))
    expect(prices[0]).toBe(Math.min(...prices))
    expect(DEMO_OPTIONS.length).toBeGreaterThan(1)
  })

  test.each(DEMO_OPTIONS.map((o, i) => [i, o] as const))("option %i is a feasible round trip", (_, option) => {
    const { path } = option
    expect(path[path.length - 1].to).toBe(path[0].from)
    path.forEach((leg, i) => {
      expect(Date.parse(leg.arrival_at) - Date.parse(leg.departure_at)).toBe(leg.time_in_travel * 1000)
      expect(leg.from_city.id).toBe(leg.from)
      expect(leg.to_city.id).toBe(leg.to)
      if (i > 0) {
        expect(leg.from).toBe(path[i - 1].to)
        expect(Date.parse(leg.departure_at)).toBeGreaterThanOrEqual(Date.parse(path[i - 1].arrival_at))
      }
    })
  })

  test("leg durations are realistic for their mode", () => {
    const hours = (s: number) => s / 3600
    for (const leg of DEMO_OPTIONS.flatMap((o) => o.path)) {
      const h = hours(leg.time_in_travel)
      if (leg.transport_type === "PLANES") expect(h).toBeLessThanOrEqual(2.5)
      else expect(h).toBeGreaterThanOrEqual(2)
    }
  })
})
