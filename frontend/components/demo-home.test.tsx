import { act, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest"

import { DEMO_SEARCH_MS, DEMO_SHOWCASE_MS } from "@/lib/demo-trips"

import { DemoHome } from "./demo-home"

vi.mock("@/components/europe-loader", () => ({
  EuropeLoader: ({
    loading, highlight, highlightLabels, highlightDurationMs,
  }: {
    loading: boolean
    highlight?: unknown[]
    highlightLabels?: string[]
    highlightDurationMs?: number
  }) => (
    <div
      data-testid="loader"
      data-loading={loading}
      data-highlight={highlight?.length ?? 0}
      data-labels={highlightLabels?.join(">") ?? ""}
      data-duration={highlightDurationMs}
    />
  ),
}))
vi.mock("@/components/cloud-overlay", () => ({ CloudOverlay: () => null }))
vi.mock("@/components/site-header", () => ({ SiteHeader: () => <header>Header</header> }))
vi.mock("@/lib/europe-cities", () => ({
  fold: (s: string) => s.toLowerCase().trim(),
  popularEuropeCities: () => Promise.resolve([]),
  searchEuropeCities: () => Promise.resolve([]),
}))
vi.mock("@/components/trip-inputs", () => ({
  EMPTY_TRIP_INPUTS: { travelers: 1 },
  TripInputs: ({ onSubmit, value }: { onSubmit: (v: unknown) => void; value: { departure?: { name: string } | null } }) => (
    <>
      <output data-testid="departure">{value.departure?.name ?? ""}</output>
      <button onClick={() => onSubmit(value)}>Search</button>
    </>
  ),
}))

describe("DemoHome", () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  test("starts like the homepage, departing from Vilnius", () => {
    render(<DemoHome />)
    expect(screen.getByTestId("departure")).toHaveTextContent("Vilnius")
    expect(screen.getByTestId("page-content")).not.toHaveAttribute("inert")
    expect(screen.queryByRole("region", { name: "Travel opportunities" })).toBeNull()
  })

  test("shows the static route for exactly 5 seconds, then the results", async () => {
    render(<DemoHome />)
    fireEvent.click(screen.getByText("Search"))
    expect(screen.getByTestId("loader")).toHaveAttribute("data-loading", "true")

    await act(async () => void vi.advanceTimersByTime(DEMO_SEARCH_MS))
    const loader = screen.getByTestId("loader")
    expect(loader).toHaveAttribute("data-highlight", "6")
    expect(loader).toHaveAttribute("data-labels", "Vilnius>Warsaw>Berlin>Stockholm>Riga>Vilnius")
    expect(loader).toHaveAttribute("data-duration", String(DEMO_SHOWCASE_MS))
    expect(screen.getByTestId("page-content")).toHaveAttribute("inert")

    await act(async () => void vi.advanceTimersByTime(DEMO_SHOWCASE_MS - 1))
    expect(screen.getByTestId("page-content")).toHaveAttribute("inert")

    await act(async () => void vi.advanceTimersByTime(1))
    expect(screen.getByTestId("page-content")).not.toHaveAttribute("inert")
    expect(screen.getByRole("region", { name: "Travel opportunities" })).toBeInTheDocument()
  })

  test("highlights the Vilnius round trip as the best match and labels the data as demo", async () => {
    render(<DemoHome />)
    fireEvent.click(screen.getByText("Search"))
    await act(async () => void vi.advanceTimersByTime(DEMO_SEARCH_MS + DEMO_SHOWCASE_MS))
    const featured = document.querySelectorAll('[data-featured="true"]')
    expect(featured).toHaveLength(1)
    expect(featured[0]).toHaveTextContent("Best match")
    expect(featured[0]).toHaveTextContent("Warsaw")
    expect(featured[0]).toHaveTextContent("Stockholm")
    expect(screen.getByText(/Demo data/)).toBeInTheDocument()
  })
})
