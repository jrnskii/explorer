import { act, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest"

import Home from "./page"

vi.mock("@/components/europe-loader", () => ({
  EuropeLoader: ({ loading, satellite }: { loading: boolean; satellite: boolean }) => (
    <div data-testid="loader" data-loading={loading} data-satellite={satellite} />
  ),
}))
vi.mock("@/components/cloud-overlay", () => ({
  CloudOverlay: () => <canvas data-testid="clouds" />,
}))
vi.mock("@/components/site-header", () => ({
  SiteHeader: () => <header>Header</header>,
}))
vi.mock("@/components/trip-opportunities", () => ({
  TripOpportunities: () => <section>Results</section>,
}))
vi.mock("@/lib/europe-cities", () => ({
  popularEuropeCities: () => Promise.resolve([]),
  searchEuropeCities: () => Promise.resolve([]),
}))
vi.mock("@/components/trip-inputs", () => ({
  EMPTY_TRIP_INPUTS: { travelers: 3 },
  TripInputs: ({ onSubmit, value }: { onSubmit: (v: { travelers: number }) => void; value: { travelers: number } }) => (
    <button onClick={() => onSubmit(value)}>Search</button>
  ),
}))

describe("Home search", () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  test("shows everything while idle", () => {
    render(<Home />)
    const content = screen.getByTestId("page-content")
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

  test("draws the cloud overlay over the map", () => {
    render(<Home />)
    expect(screen.getByTestId("clouds")).toBeInTheDocument()
  })

  test("hides everything but the map while searching, then restores the page with results", async () => {
    render(<Home />)
    fireEvent.click(screen.getByText("Search"))
    const content = screen.getByTestId("page-content")
    expect(content).toHaveAttribute("inert")
    expect(content).toHaveClass("opacity-0")
    expect(screen.getByTestId("loader")).toHaveAttribute("data-loading", "true")
    expect(screen.queryByText("Results")).toBeNull()

    await act(async () => void vi.advanceTimersByTime(10000))
    expect(content).not.toHaveAttribute("inert")
    expect(content).not.toHaveClass("opacity-0")
    expect(screen.getByText("Results")).toBeInTheDocument()
  })
})
