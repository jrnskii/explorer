import { afterEach, describe, expect, test, vi } from "vitest"
import { EMPTY_TRIP_INPUTS, type TripInputsValue } from "@/components/trip-inputs"
import { searchRoundTrips, toRoundTripInput } from "./round-trip-search"
import { SAMPLE_OPTIONS } from "@/components/trip-opportunities.preview"

const value: TripInputsValue = {
  ...EMPTY_TRIP_INPUTS, departure: { id: "gn-756135", name: "Warsaw", country: "Poland" },
  date: new Date(2027, 0, 1), duration: "3", budget: "200.01",
}
afterEach(() => vi.unstubAllGlobals())

describe("shared search input mapping", () => {
  test("accepts every canonical city, including Vilnius, without a city allowlist", () => {
    const result = toRoundTripInput({ ...value, departure: { id: "gn-593116", name: "Vilnius", country: "Lithuania" } })
    expect(result.departure_city).toBe("gn-593116")
  })

  test("uses canonical IDs, offset timestamps, string decimals and hard duration", () => {
    const result = toRoundTripInput(value)
    expect(result.departure_city).toBe("gn-756135")
    expect(result).not.toHaveProperty("expenses_tolerance")
    expect(result.departure_timezone).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone)
    expect(Date.parse(result.departure_date)).toBe(new Date(2027, 0, 1).getTime())
    expect(result.departure_date).toMatch(/^2027-01-01T00:00:00[+-]\d{2}:\d{2}$/)
    expect(result.max_trip_duration).toBe(3 * 86400)
    expect(result.time_tolerance).toBe(3 * 1440)
  })
  test("maps duration ranges and caps return windows", () => {
    const result = toRoundTripInput({ ...value, duration: "2-5", returnDate: new Date(2027, 0, 3) })
    expect(Date.parse(result.desired_arrival_date)).toBe(new Date(2027, 0, 3, 23, 59, 59).getTime())
    expect(result.time_tolerance).toBe(1439)
  })
  test.each([
    { travelers: 2 }, { daysPerCity: "2" },
    { duration: "5-2" }, { duration: "367" },
    { departure: { id: "vno", name: "Vilnius", country: "Lithuania" } },
    { returnDate: new Date(2026, 0, 1) },
  ])("rejects unrepresentable or invalid constraints: %j", (patch) => {
    expect(() => toRoundTripInput({ ...value, ...patch })).toThrow()
  })
  test("omits the optional minimum-city filter when blank", () => {
    expect(toRoundTripInput({ ...value, numberOfCities: "" })).not.toHaveProperty("min_cities")
  })
  test.each([["1", 1], ["3", 3], ["99", 99]])("ignores retired minimum cities %s (%i)", (numberOfCities) => {
    expect(toRoundTripInput({ ...value, numberOfCities: String(numberOfCities), budget: "", flexibleDates: true })).not.toHaveProperty("min_cities")
  })
  test("maps mandatory and excluded cities", () => {
    const result = toRoundTripInput({ ...value,
      mustVisit: [{ id: "gn-2988507", name: "Paris", country: "France" }],
      avoid: [{ id: "gn-2759794", name: "Amsterdam", country: "Netherlands" }],
    })
    expect(result.mandatory_cities).toEqual(["gn-2988507"])
    expect(result.excluded_cities).toEqual(["gn-2759794"])
  })
})

describe("search transport", () => {
  test("retains an over-budget option and reports its badge and notice", async () => {
    const options = SAMPLE_OPTIONS.slice(0, 1)
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({
      data: { round_trip_options: options }, extensions: {
        price_status: "over_budget", option_pricing: [{ price_status: "provider_advertised", over_budget: true }],
      },
    })))
    const notice = vi.fn()
    expect(await searchRoundTrips({ ...value, budget: "1" }, undefined, notice)).toEqual(options)
    expect(notice).toHaveBeenCalledWith(expect.stringContaining("shown below"), ["provider_advertised"], [true], [], [1], false)
  })
  test("sends no city-count filter when the optional field is blank", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ data: { round_trip_options: [] } }))
    vi.stubGlobal("fetch", fetcher)
    await searchRoundTrips({ ...value, numberOfCities: "" })
    expect(JSON.parse(fetcher.mock.calls[0][1].body).input).not.toHaveProperty("min_cities")
  })
  test("posts to the same-origin route without credentials and preserves cancellation", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ data: { round_trip_options: [] } }))
    vi.stubGlobal("fetch", fetcher)
    const signal = new AbortController().signal
    expect(await searchRoundTrips({ ...value, numberOfCities: "3" }, signal)).toEqual([])
    expect(fetcher).toHaveBeenCalledWith("/api/round-trip", expect.objectContaining({ signal }))
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ input: toRoundTripInput({ ...value, numberOfCities: "3" }) })
    expect(fetcher.mock.calls[0][1].headers).not.toHaveProperty("Authorization")
  })
  test.each([
    { errors: [{ message: "Invalid constraints" }] }, { data: null }, { error: "Unavailable" },
    null, { data: { round_trip_options: [{}] } },
  ])("handles GraphQL and malformed responses", async (payload) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(payload)))
    await expect(searchRoundTrips(value)).rejects.toThrow()
  })
})

test("reports provider coverage and search bounds to the user", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ data: { round_trip_options: [] },
    extensions: { unavailable_transport_types: ["PLANES"], results_limited: true } })))
  const notice = vi.fn()
  await searchRoundTrips(value, undefined, notice)
  expect(notice).toHaveBeenCalledWith(expect.stringContaining("Flight schedules"), [], [], [], [], false)
  expect(notice).toHaveBeenCalledWith(expect.stringContaining("limit"), [], [], [], [], false)
})

test("retains per-option checked versus forecast price status", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ data: { round_trip_options: [] },
    extensions: { price_status: "unavailable", option_pricing: [] } })))
  const notice = vi.fn()
  await searchRoundTrips(value, undefined, notice)
  expect(notice).toHaveBeenCalledWith(expect.stringContaining("best opportunity"), [], [], [], [], false)
})

test("delivers estimate-only routes instead of treating them as empty results", async () => {
  const estimate = { rank: 1, cities: [{ id: "a", name: "Home" }, { id: "b", name: "Riga" }, { id: "c", name: "Tallinn" }, { id: "a", name: "Home" }], departure_date: "2030-01-02", return_date: "2030-01-04", total_price: { amount: "30.50", currency: "EUR" }, transport_types: ["TRAINS" as const, "TRAINS" as const, "TRAINS" as const], schedule_source: "reference" }
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ data: { round_trip_options: [] }, extensions: { estimated_routes: [estimate], price_status: "unavailable" } })))
  const notice = vi.fn()
  await searchRoundTrips(value, undefined, notice)
  expect(notice).toHaveBeenCalledWith(expect.stringContaining("remain estimates"), [], [], [estimate], [], false)
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ data: { round_trip_options: [] }, extensions: { estimated_routes: [{ ...estimate, total_price: { amount: "NaN", currency: "EUR" } }] } })))
  await expect(searchRoundTrips(value)).rejects.toThrow("invalid estimated routes")
})

test.each([true, false, undefined, "true"])("passes strict cache metadata (%s)", async (cached) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
    data: { round_trip_options: [] }, extensions: { provider_results_cached: cached },
  }))))
  const notice = vi.fn()
  await searchRoundTrips(value, undefined, notice)
  expect(notice).toHaveBeenCalledWith("", [], [], [], [], cached === true)
})

test.each([[], ["TRAINS"], ["TRAINS", "ROCKET", "BUSSES"]].map(transport_types => ({ transport_types })))("rejects inconsistent estimated transport types ($transport_types)", async ({ transport_types }) => {
  const estimate = {
    rank: 1, cities: ["Paris", "Berlin", "Rome", "Paris"].map(name => ({ id: name, name })),
    departure_date: "2030-01-01", return_date: "2030-01-04",
    total_price: { amount: "30", currency: "EUR" }, schedule_source: "reference", transport_types,
  }
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ data: { round_trip_options: [] }, extensions: { estimated_routes: [estimate] } })))
  await expect(searchRoundTrips(value)).rejects.toThrow("invalid estimated routes")
})

test("sends only the selected transport types for route estimation", () => {
  expect(toRoundTripInput({ ...value, modes: ["TRAINS", "BUSSES"] }).transport_types).toEqual(["TRAINS", "BUSSES"])
})

test.each([undefined, null])("accepts older estimated routes without transport types (%s)", async (transport_types) => {
  const estimate = {
    rank: 1, cities: ["Paris", "Berlin", "Rome", "Paris"].map(name => ({ id: name, name })),
    departure_date: "2030-01-01", return_date: "2030-01-04",
    total_price: { amount: "30", currency: "EUR" }, schedule_source: "reference", transport_types,
  }
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ data: { round_trip_options: [] }, extensions: { estimated_routes: [estimate] } })))
  const notice = vi.fn()
  await searchRoundTrips(value, undefined, notice)
  expect(notice.mock.calls[0][3]).toEqual([estimate])
})
