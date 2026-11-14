import { act, render } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest"

import { EuropeLoader } from "./europe-loader"

// Leaflet needs a real layout engine; replace the map with a linear projection.
vi.mock("next/dynamic", () => ({
  default: () =>
    function FakeMap({
      fit,
      children,
    }: {
      fit: unknown
      children: (api: {
        project: (p: readonly [number, number]) => [number, number]
        width: number
        height: number
      }) => ReactNode
    }) {
      void fit
      return (
        <div>
          {children({
            project: ([lon, lat]) => [lon * 10 + 300, 800 - lat * 10],
            width: 1000,
            height: 800,
          })}
        </div>
      )
    },
}))

function mockMotion(reduce: boolean) {
  vi.stubGlobal(
    "matchMedia",
    (query: string) => ({ matches: reduce && query.includes("reduce"), media: query })
  )
}

const beams = (c: HTMLElement) => c.querySelectorAll(".eu-beam")
const lines = (c: HTMLElement) => c.querySelectorAll(".eu-draw")

describe("EuropeLoader route shimmer", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mockMotion(false)
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  test("draws nothing until loading starts", () => {
    const { container, rerender } = render(<EuropeLoader loading={false} />)
    act(() => void vi.advanceTimersByTime(50))
    expect(lines(container)).toHaveLength(0)

    rerender(<EuropeLoader loading />)
    act(() => void vi.advanceTimersByTime(50))
    // Origin fan-out plus the routes that continue from each arrival city.
    expect(lines(container).length).toBeGreaterThanOrEqual(5)
    expect(lines(container).length).toBeLessThanOrEqual(30)
  })

  test("each route has a trail, haloed head and arrival light", () => {
    const { container } = render(<EuropeLoader loading />)
    act(() => void vi.advanceTimersByTime(50))
    const n = lines(container).length
    expect(beams(container)).toHaveLength(n * 7)
    expect(container.querySelectorAll(".eu-arrive")).toHaveLength(n)
    // No SVG filters: blur would repaint every frame.
    expect(container.querySelectorAll("filter, [filter]")).toHaveLength(0)
  })

  test("does not draw capital dots", () => {
    const dots = (c: HTMLElement) => c.querySelectorAll('svg circle[r="3.5"]')
    const { container, rerender } = render(<EuropeLoader loading={false} />)
    expect(dots(container)).toHaveLength(0)

    rerender(<EuropeLoader loading />)
    act(() => void vi.advanceTimersByTime(50))
    expect(dots(container)).toHaveLength(0)
    // Routes are still drawn.
    expect(lines(container).length).toBeGreaterThan(0)
  })

  test("uses real destinations when provided", () => {
    const { container } = render(
      <EuropeLoader
        loading
        destinations={[
          { lon: 2.35, lat: 48.85 },
          { lon: 12.5, lat: 41.9 },
          { lon: 500, lat: 500 },
        ]}
      />
    )
    act(() => void vi.advanceTimersByTime(50))
    expect(lines(container)).toHaveLength(2)
  })

  test("routes continue from the cities earlier routes arrived at", () => {
    const { container } = render(<EuropeLoader loading />)
    act(() => void vi.advanceTimersByTime(50))
    const delays = [...lines(container)].map((p) =>
      parseFloat((p as HTMLElement).parentElement!.style.getPropertyValue("--delay"))
    )
    expect(Math.max(...delays)).toBeGreaterThan(2000)
    expect(delays.filter((d) => d === 0)).toHaveLength(1)
  })

  test("never shows two rounds at once and keeps looping while loading", () => {
    const { container } = render(<EuropeLoader loading />)
    for (let i = 0; i < 6; i++) {
      act(() => void vi.advanceTimersByTime(1000))

      expect(lines(container).length).toBeLessThanOrEqual(30)
    }
  })

  test("fades and removes routes when the search completes", () => {
    const { container, rerender } = render(<EuropeLoader loading />)
    act(() => void vi.advanceTimersByTime(50))
    rerender(<EuropeLoader loading={false} />)
    expect(container.querySelector(".eu-fade-out")).not.toBeNull()
    act(() => void vi.advanceTimersByTime(1000))
    expect(lines(container)).toHaveLength(0)
  })

  test("restarting a search does not stack animations", () => {
    const { container, rerender } = render(<EuropeLoader loading />)
    act(() => void vi.advanceTimersByTime(500))
    rerender(<EuropeLoader loading={false} />)
    rerender(<EuropeLoader loading />)
    act(() => void vi.advanceTimersByTime(50))
    expect(lines(container).length).toBeLessThanOrEqual(30)
  })

  test("reduced motion shows a single static round", () => {
    mockMotion(true)
    const { container } = render(<EuropeLoader loading />)
    act(() => void vi.advanceTimersByTime(50))
    const first = lines(container).length
    expect(first).toBeGreaterThan(0)
    act(() => void vi.advanceTimersByTime(30000))
    expect(lines(container)).toHaveLength(first)
  })
})
