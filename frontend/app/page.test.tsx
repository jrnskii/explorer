import { act, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest"

import { highlightTimeline } from "@/lib/europe-route-wave"

import Home from "./page"
import type { RoundTripOption } from "@/generated/schema_v1"
import { SAMPLE_OPTIONS } from "@/components/trip-opportunities.preview"

// Sample trip: Vilnius > Riga > Tallinn > Vilnius, i.e. four stops.
const SHOWCASE_MS = highlightTimeline([[0, 0], [1, 1], [2, 2], [3, 3]]).endMs

vi.mock("@/components/europe-loader", () => ({
  EuropeLoader: ({
    loading,
    satellite,
    highlight,
    highlightLabels,
    onFlight,
  }: {
    loading: boolean
    satellite: boolean
    highlight?: unknown[]
    highlightLabels?: string[]
    onFlight?: (flying: boolean) => void
  }) => (
    <div
      data-testid="loader"
      onClick={() => onFlight?.(true)}
      onDoubleClick={() => onFlight?.(false)}
      data-loading={loading}
      data-satellite={satellite}
      data-highlight={highlight?.length ?? 0}
      data-labels={highlightLabels?.join(">") ?? ""}
    />
  ),
}))
vi.mock("@/components/cloud-overlay", () => ({
  CloudOverlay: ({ denseTop, density }: { denseTop?: boolean; density?: number }) => (
    <canvas data-testid="clouds" data-dense-top={String(!!denseTop)} data-density={density} />
  ),
}))
vi.mock("@/components/site-header", () => ({
  SiteHeader: () => <header>Header</header>,
}))
vi.mock("@/components/trip-opportunities", () => ({
  TripOpportunities: () => <section>Results</section>,
}))
vi.mock("@/lib/europe-cities", () => ({
  fold: (s: string) => s.toLowerCase().trim(),
  popularEuropeCities: () => Promise.resolve([]),
  searchEuropeCities: () => Promise.resolve([]),
}))
const { detectDepartureCity, searchRoundTrips } = vi.hoisted(() => ({
  searchRoundTrips: vi.fn<(value: unknown, signal?: AbortSignal) => Promise<RoundTripOption[]>>(() => new Promise(() => {})),
  detectDepartureCity: vi.fn(() => Promise.resolve(null as unknown)),
}))
vi.mock("@/lib/ip-origin", () => ({ detectDepartureCity }))
vi.mock("@/lib/round-trip-search", () => ({ searchRoundTrips }))
vi.mock("@/components/trip-inputs", () => ({
  EMPTY_TRIP_INPUTS: { travelers: 3 },
  TripInputs: ({ onSubmit, value }: { onSubmit: (v: { travelers: number }) => void; value: { travelers: number; departure?: { name: string } | null; date?: Date; duration?: string; budget?: string } }) => (
    <>
      <output data-testid="defaults">{`${value.date?.toDateString()}|${value.duration}|${value.budget}`}</output>
      <output data-testid="departure">{value.departure?.name ?? ""}</output>
      <button onClick={() => onSubmit(value)}>Search</button>
    </>
  ),
}))

describe("Home default trip", () => {
  afterEach(() => vi.useRealTimers())

  test("starts in 2 days, lasts 3 days, without a budget", async () => {
    vi.useFakeTimers({ toFake: ["Date"] })
    vi.setSystemTime(new Date(2026, 11, 30, 15, 30))
    render(<Home />)
    await act(async () => {})
    expect(screen.getByTestId("defaults")).toHaveTextContent(
      `${new Date(2027, 0, 1).toDateString()}|3|undefined`
    )
  })
})

describe("Home departure from IP", () => {
  test("pre-fills the departure with the detected capital", async () => {
    detectDepartureCity.mockResolvedValueOnce({ id: "gn-1", name: "Vilnius", country: "Lithuania" })
    render(<Home />)
    expect(await screen.findByText("Vilnius")).toBeInTheDocument()
  })

  test("leaves the departure empty when nothing is detected", async () => {
    detectDepartureCity.mockResolvedValueOnce(null)
    render(<Home />)
    await act(async () => {})
    expect(screen.getByTestId("departure")).toBeEmptyDOMElement()
  })
})

describe("Home search", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    searchRoundTrips.mockResolvedValue([SAMPLE_OPTIONS[0]])
  })
  afterEach(() => vi.useRealTimers())

  test("shows everything while idle", () => {
    render(<Home />)
    const content = screen.getByTestId("page-content")
    expect(screen.queryByText(/Sample itineraries with estimated fares/)).not.toBeInTheDocument()
    expect(content).not.toHaveAttribute("inert")
    expect(content).not.toHaveClass("opacity-0")
  })

  test("always shows satellite imagery: idle, searching, and with results", () => {
    render(<Home />)
    expect(screen.getByTestId("loader")).toHaveAttribute("data-satellite", "true")
    fireEvent.click(screen.getByText("Search"))
    expect(screen.getByTestId("loader")).toHaveAttribute("data-satellite", "true")
    act(() => void vi.advanceTimersByTime(10000))
    expect(screen.getByTestId("loader")).toHaveAttribute("data-satellite", "true")
  })

  test("fades the backdrop blur out while the map zooms and back in after", () => {
    const { container } = render(<Home />)
    const blur = () => container.querySelector("[data-flying]") as HTMLElement
    expect(blur()).not.toHaveClass("opacity-0")
    fireEvent.click(screen.getByTestId("loader"))
    expect(blur()).toHaveClass("opacity-0")
    fireEvent.doubleClick(screen.getByTestId("loader"))
    expect(blur()).not.toHaveClass("opacity-0")
  })

  test("keeps the clouds unchanged through the search and the zoom, thickening them with the results", async () => {
    render(<Home />)
    const dense = () => screen.getByTestId("clouds").getAttribute("data-dense-top")
    expect(dense()).toBe("true")

    fireEvent.click(screen.getByText("Search"))
    expect(dense()).toBe("false")

    // Search finished: the map zooms onto the path, clouds stay as they were.
    await act(async () => void vi.advanceTimersByTime(10000))
    expect(screen.queryByText("Results")).toBeNull()
    expect(dense()).toBe("false")

    await act(async () => void vi.advanceTimersByTime(SHOWCASE_MS))
    expect(screen.getByText("Results")).toBeInTheDocument()
    expect(dense()).toBe("true")
  })

  test("thins the clouds to 0.75 while the map zooms", () => {
    render(<Home />)
    const density = () => screen.getByTestId("clouds").getAttribute("data-density")
    expect(density()).toBe("1")
    fireEvent.click(screen.getByTestId("loader"))
    expect(density()).toBe("0.75")
    fireEvent.doubleClick(screen.getByTestId("loader"))
    expect(density()).toBe("1")
  })

  test("draws the cloud overlay over the map", () => {
    render(<Home />)
    expect(screen.getByTestId("clouds")).toBeInTheDocument()
  })

  test("hides everything but the map while searching, then restores the page with results", async () => {
    let finish: ((value: never[]) => void) | undefined
    searchRoundTrips.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    render(<Home />)
    fireEvent.click(screen.getByText("Search"))
    const content = screen.getByTestId("page-content")
    expect(content).toHaveAttribute("inert")
    expect(content).toHaveClass("opacity-0")
    expect(screen.getByTestId("loader")).toHaveAttribute("data-loading", "true")
    expect(screen.queryByText("Results")).toBeNull()

    await act(async () => { finish?.([]) })
    expect(content).not.toHaveAttribute("inert")
    expect(content).not.toHaveClass("opacity-0")
    expect(screen.getByText("Results")).toBeInTheDocument()
  })

  test("holds the results back until the white path has drawn and faded out over 3 seconds", async () => {
    render(<Home />)
    fireEvent.click(screen.getByText("Search"))
    await act(async () => void vi.advanceTimersByTime(10000))
    const content = screen.getByTestId("page-content")
    expect(screen.getByTestId("loader")).toHaveAttribute("data-highlight", "4")
    expect(content).toHaveAttribute("inert")
    expect(screen.queryByText("Results")).toBeNull()

    await act(async () => void vi.advanceTimersByTime(SHOWCASE_MS - 1))
    expect(screen.queryByText("Results")).toBeNull()
    await act(async () => void vi.advanceTimersByTime(1))
    expect(screen.getByText("Results")).toBeInTheDocument()

    // A new search hides the results again and waits again.
    fireEvent.click(screen.getByText("Search"))
    await act(async () => void vi.advanceTimersByTime(10000))
    expect(screen.queryByText("Results")).toBeNull()
    await act(async () => void vi.advanceTimersByTime(SHOWCASE_MS))
    expect(screen.getByText("Results")).toBeInTheDocument()
  })

  test("highlights the cheapest trip only after results arrive", async () => {
    render(<Home />)
    fireEvent.click(screen.getByText("Search"))
    expect(screen.getByTestId("loader")).toHaveAttribute("data-highlight", "0")

    await act(async () => void vi.advanceTimersByTime(10000))
    // Vilnius > Riga > Tallinn > Vilnius: all capitals.
    expect(screen.getByTestId("loader")).toHaveAttribute("data-highlight", "4")
    expect(screen.getByTestId("loader")).toHaveAttribute(
      "data-labels",
      "Vilnius>Riga>Tallinn>Vilnius"
    )

    fireEvent.click(screen.getByText("Search"))
    expect(screen.getByTestId("loader")).toHaveAttribute("data-highlight", "0")
  })

})

test("shows a search error and allows retry to empty results", async () => {
  searchRoundTrips.mockRejectedValueOnce(new Error("Search is unavailable"))
  render(<Home />)
  fireEvent.click(screen.getByText("Search"))
  expect(await screen.findByRole("alert")).toHaveTextContent("Search is unavailable")
  expect(screen.getByTestId("page-content")).not.toHaveAttribute("inert")
  searchRoundTrips.mockResolvedValueOnce([])
  fireEvent.click(screen.getByText("Search"))
  expect(await screen.findByText("Results")).toBeInTheDocument()
  expect(screen.queryByRole("alert")).toBeNull()
  expect(screen.getByText(/Up to 10 cheapest/)).toHaveAttribute("role", "status")
})

test("aborts a pending search on unmount", () => {
  const { unmount } = render(<Home />)
  fireEvent.click(screen.getByText("Search"))
  const signal = searchRoundTrips.mock.calls.at(-1)?.[1] as AbortSignal | undefined
  unmount()
  expect(signal?.aborted).toBe(true)
})
