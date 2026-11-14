import { afterEach, describe, expect, mock, spyOn, test } from "bun:test"
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react"
import type { TripInputsValue } from "@/components/trip-inputs"
import { SAMPLE_OPTIONS } from "@/components/trip-opportunities.preview"
import { applyFareEstimates, fetchFareEstimates } from "@/lib/forecast-pricing"
import { prepareSamples, priceSamples } from "@/lib/sample-forecast"

const input: TripInputsValue = {
  departure: { id: "vno", name: "Vilnius", country: "Lithuania", code: "VNO" },
  budget: "1000", date: new Date(2030, 11, 4), duration: "7", flexibleDates: false,
  travelers: 2, modes: ["PLANES", "BUSSES", "TRAINS", "FERRIES"], numberOfCities: "",
  returnDate: undefined, daysPerCity: "", mustVisit: [], avoid: [],
}
const estimate = (amount: string) => ({ price: { amount, currency: "EUR" }, model_id: "fixture", warnings: ["Estimate only"] })
let fetchSpy: ReturnType<typeof spyOn<typeof globalThis, "fetch">> | undefined

function implementation(fn: (...args: Parameters<typeof fetch>) => ReturnType<typeof fetch>): typeof fetch {
  return Object.assign(fn, { preconnect: () => {} })
}

afterEach(() => { cleanup(); fetchSpy?.mockRestore(); fetchSpy = undefined })

describe("forecast pricing", () => {
  test("sums separate ticket estimates exactly and removes any unpriced itinerary", () => {
    const options = SAMPLE_OPTIONS.slice(0, 1)
    expect(applyFareEstimates(options, [estimate("0.10"), estimate("0.20"), estimate("0.30")])[0].total_price.amount).toBe("0.60")
    expect(applyFareEstimates(options, [estimate("1.00"), null, estimate("1.00")])).toEqual([])
    expect(() => applyFareEstimates(options, [])).toThrow("Missing")
    expect(options[0].total_price.amount).toBe("89.90")
  })
  test("filters modes, home and constraints while shifting to the selected calendar date", () => {
    const options = prepareSamples(SAMPLE_OPTIONS, { ...input, modes: ["PLANES"] })
    expect(options).toHaveLength(1)
    expect(options[0].path[0].departure_at.slice(0, 10)).toBe("2030-12-04")
    expect(prepareSamples(SAMPLE_OPTIONS, { ...input, departure: { id: "par", name: "Paris", country: "France", code: "PAR" } })).toEqual([])
    expect(prepareSamples(SAMPLE_OPTIONS, { ...input, mustVisit: [{ id: "xx", name: "Unknown", country: "France", code: "XXX" }] })).toEqual([])
    expect(() => prepareSamples(SAMPLE_OPTIONS, { ...input, flexibleDates: true })).toThrow("fixed dates")
  })
  test("fetches party forecasts, applies budget and never uses the preview price", async () => {
    fetchSpy = spyOn(globalThis, "fetch").mockImplementation(implementation(async (_url, init) => {
      const payload = JSON.parse(String(init?.body))
      expect(payload.queries.every((q: { travelers: number }) => q.travelers === 2)).toBe(true)
      return Response.json({ forecasts: payload.queries.map(() => estimate("10.00")) })
    }))
    const options = await priceSamples(SAMPLE_OPTIONS, { ...input, budget: "20.00", modes: ["PLANES"] })
    expect(options).toHaveLength(1)
    expect(options[0].total_price).toEqual({ amount: "20.00", currency: "EUR" })
  })
  test("rejects failed, malformed and non-EUR responses without fallback", async () => {
    const queries = [{ mode: "PLANES" as const, origin: "Paris", destination: "Rome", departure_date: "2030-12-04" }]
    fetchSpy = spyOn(globalThis, "fetch").mockResolvedValue(Response.json({}, { status: 503 }))
    await expect(fetchFareEstimates(queries)).rejects.toThrow("unavailable")
    fetchSpy.mockResolvedValue(Response.json({ forecasts: [estimate("NaN")] }))
    await expect(fetchFareEstimates(queries)).rejects.toThrow("Invalid")
    fetchSpy.mockResolvedValue(Response.json({ forecasts: [{ ...estimate("10.00"), price: { amount: "10.00", currency: "USD" } }] }))
    await expect(fetchFareEstimates(queries)).rejects.toThrow("Invalid")
    fetchSpy.mockResolvedValue(Response.json({ forecasts: [] }))
    await expect(fetchFareEstimates(queries)).rejects.toThrow("Invalid")
  })
})

// Keep the existing form's internal interaction tests out of this price-integration boundary.
mock.module("@/components/trip-inputs", () => ({
  EMPTY_TRIP_INPUTS: input,
  TripInputs: ({ onSubmit, loading }: { onSubmit: (value: TripInputsValue) => void; loading: boolean }) =>
    <button disabled={loading} onClick={() => onSubmit(input)}>Estimate fares</button>,
}))
const { default: Home } = await import("@/app/page")

test("page shows loading, renders party totals once, and labels synthetic itineraries", async () => {
  let finish: ((value: Response) => void) | undefined
  fetchSpy = spyOn(globalThis, "fetch").mockImplementation(implementation(() => new Promise<Response>((resolve) => { finish = resolve })))
  render(<Home />)
  fireEvent.click(screen.getByRole("button", { name: "Estimate fares" }))
  expect(screen.getByRole("region", { name: "Travel opportunities" }).getAttribute("aria-busy")).toBe("true")
  const payload = JSON.parse(String(fetchSpy.mock.calls[0][1]?.body))
  await act(async () => { finish?.(Response.json({ forecasts: payload.queries.map(() => estimate("10.00")) })) })
  expect((await screen.findAllByText("estimated total for 2 travellers")).length).toBeGreaterThan(0)
  expect(screen.getAllByText("€20").length).toBeGreaterThan(0)
  expect(screen.getByText(/Schedules are illustrative, not bookable/)).toBeDefined()
})

test("page announces pricing errors and recovers on another submission", async () => {
  fetchSpy = spyOn(globalThis, "fetch").mockResolvedValue(Response.json({}, { status: 503 }))
  render(<Home />)
  fireEvent.click(screen.getByRole("button", { name: "Estimate fares" }))
  expect((await screen.findByRole("alert")).textContent).toContain("unavailable")
  fetchSpy.mockImplementation(implementation(async (_url, init) => {
    const payload = JSON.parse(String(init?.body))
    return Response.json({ forecasts: payload.queries.map(() => null) })
  }))
  fireEvent.click(screen.getByRole("button", { name: "Estimate fares" }))
  await screen.findByText("No travel opportunities match your search")
  expect(screen.queryByRole("alert")).toBeNull()
})
