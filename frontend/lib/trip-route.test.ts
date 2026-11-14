import { describe, expect, test, vi } from "vitest"

import type { RoundTripOption } from "@/generated/schema_v1"

import { cheapestOption, locateStops, stopNames } from "./trip-route"

const leg = (from: string, to: string) => ({
  from,
  to,
  departure_at: "2026-12-04T07:00:00Z",
  arrival_at: "2026-12-04T09:00:00Z",
  time_in_travel: 7200,
  transport_type: "PLANES" as const,
})

const option = (amount: string, currency = "EUR", ...cities: string[]) =>
  ({
    total_price: { amount, currency },
    path: cities.slice(1).map((c, i) => leg(cities[i], c)),
  }) as RoundTripOption

describe("cheapestOption", () => {
  test("picks the lowest price regardless of order and string length", () => {
    const a = option("89.90", "EUR", "Vilnius", "Riga", "Vilnius")
    const b = option("1000", "EUR", "Vilnius", "Rome", "Vilnius")
    const c = option("9.5", "EUR", "Vilnius", "Berlin", "Vilnius")
    expect(cheapestOption([a, b, c])).toBe(c)
  })

  test("keeps the earliest option on a tie", () => {
    const a = option("50", "EUR", "Vilnius", "Riga", "Vilnius")
    const b = option("50.00", "EUR", "Vilnius", "Rome", "Vilnius")
    expect(cheapestOption([a, b])).toBe(a)
  })

  test("returns null for no options, mixed currencies or invalid amounts", () => {
    expect(cheapestOption([])).toBeNull()
    expect(
      cheapestOption([option("10", "EUR", "A", "B"), option("5", "USD", "A", "B")])
    ).toBeNull()
    expect(cheapestOption([option("abc", "EUR", "A", "B")])).toBeNull()
  })

  test("treats a zero price as the cheapest", () => {
    const free = option("0", "EUR", "Vilnius", "Riga", "Vilnius")
    expect(cheapestOption([option("5", "EUR", "A", "B"), free])).toBe(free)
  })
})

describe("stopNames", () => {
  test("lists the origin, every arrival and the return", () => {
    expect(stopNames(option("1", "EUR", "Vilnius", "Riga", "Tallinn", "Vilnius"))).toEqual([
      "Vilnius",
      "Riga",
      "Tallinn",
      "Vilnius",
    ])
  })

  test("is empty for an empty path", () => {
    expect(stopNames({ total_price: { amount: "1", currency: "EUR" }, path: [] })).toEqual([])
  })
})

describe("locateStops", () => {
  const noSearch = vi.fn(() => Promise.resolve([]))

  test("resolves capitals by name, ignoring case and diacritics", async () => {
    const points = await locateStops(["vilnius", "RIGA"], null, noSearch)
    expect(points).toHaveLength(2)
    expect(points?.[0][0]).toBeCloseTo(25.28, 1)
    expect(noSearch).not.toHaveBeenCalled()
  })

  test("uses the departure coordinates and the city dataset for other cities", async () => {
    const search = vi.fn(() =>
      Promise.resolve([
        { id: "x", name: "Barcelona", country: "Spain", lat: 41.39, lon: 2.17 },
      ])
    )
    const points = await locateStops(
      ["Kaunas", "Barcelona", "Kaunas"],
      { name: "Kaunas", lon: 23.9, lat: 54.9 },
      search
    )
    expect(points).toEqual([
      [23.9, 54.9],
      [2.17, 41.39],
      [23.9, 54.9],
    ])
    expect(search).toHaveBeenCalledTimes(1)
  })

  test("returns null when a stop is unknown, ambiguous or off the map", async () => {
    expect(await locateStops(["Vilnius", "Nowhereville"], null, noSearch)).toBeNull()
    const partial = vi.fn(() =>
      Promise.resolve([{ id: "x", name: "Barcelona Heights", country: "Spain", lat: 1, lon: 1 }])
    )
    expect(await locateStops(["Barcelona"], null, partial)).toBeNull()
    const farAway = vi.fn(() =>
      Promise.resolve([{ id: "x", name: "Tokyo", country: "Japan", lat: 35.7, lon: 139.7 }])
    )
    expect(await locateStops(["Tokyo"], null, farAway)).toBeNull()
    expect(await locateStops([], null, noSearch)).toBeNull()
  })
})
