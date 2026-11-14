import { act, render } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest"

import { HIGHLIGHT_ZOOM_MS } from "@/lib/europe-route-wave"

import { EuropeLoader } from "./europe-loader"

// Leaflet needs a real layout engine; replace the map with a linear projection.
vi.mock("next/dynamic", () => ({
  default: () =>
    function FakeMap({
      fit,
      children,
    }: {
      fit: readonly (readonly [number, number])[]
      children: (api: {
        project: (p: readonly [number, number]) => [number, number]
        width: number
        height: number
      }) => ReactNode
    }) {
      return (
        <div data-testid="map" data-fit-count={fit.length} data-fit-first={fit[0]?.join(",")}>
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

describe("EuropeLoader cheapest path", () => {
  beforeEach(() => mockMotion(false))
  afterEach(() => vi.unstubAllGlobals())

  const stops = [
    [25.28, 54.69],
    [24.1, 56.95],
    [24.75, 59.44],
    [25.28, 54.69],
  ] as const
  const best = (c: HTMLElement) => c.querySelectorAll("[data-testid='cheapest-path'] g > path.eu-best")

  test("draws a glowing white leg per hop once the search is done", () => {
    const { container } = render(<EuropeLoader loading={false} highlight={stops} />)
    const legs = container.querySelectorAll("[data-testid='cheapest-path'] > g")
    expect(legs).toHaveLength(3)
    // Three glow layers plus the bright core per leg, all sharing the white route colour.
    expect(best(container)).toHaveLength(12)
    expect(container.querySelectorAll("[data-testid='cheapest-path'] .eu-best-glow")).toHaveLength(9)
    expect(
      (legs[1] as HTMLElement).style.getPropertyValue("--delay")
    ).toBe(`${HIGHLIGHT_ZOOM_MS + 700}ms`)
    expect(container.querySelectorAll("filter, [filter]")).toHaveLength(0)
  })

  test("zooms the map onto the path, and back out when it is gone", () => {
    const fitOf = (c: HTMLElement) => c.querySelector("[data-testid='map']")!
    const { container, rerender } = render(<EuropeLoader loading={false} />)
    const capitals = fitOf(container).getAttribute("data-fit-count")
    expect(Number(capitals)).toBeGreaterThan(4)

    rerender(<EuropeLoader loading={false} highlight={stops} />)
    expect(fitOf(container).getAttribute("data-fit-count")).toBe("4")
    expect(fitOf(container).getAttribute("data-fit-first")).toBe("25.28,54.69")

    rerender(<EuropeLoader loading />)
    expect(fitOf(container).getAttribute("data-fit-count")).toBe(capitals)
  })

  test("does not zoom when the path collapses to a single point", () => {
    const { container } = render(
      <EuropeLoader loading={false} highlight={[stops[0], stops[0]]} />
    )
    expect(container.querySelector("[data-testid='cheapest-path']")).toBeNull()
    expect(Number(container.querySelector("[data-testid='map']")!.getAttribute("data-fit-count"))).toBeGreaterThan(4)
  })

  test("writes each city name once, timed to the path's arrival", () => {
    const names = ["Vilnius", "Riga", "Tallinn", "Vilnius"]
    const { container } = render(
      <EuropeLoader loading={false} highlight={stops} highlightLabels={names} />
    )
    const labels = [...container.querySelectorAll(".eu-best-label")]
    expect(labels.map((l) => l.textContent)).toEqual(["Vilnius", "Riga", "Tallinn"])
    const delays = [...container.querySelectorAll(".eu-best-stop")].map((g) =>
      (g as HTMLElement).style.getPropertyValue("--delay")
    )
    expect(delays).toEqual([
      `${HIGHLIGHT_ZOOM_MS}ms`,
      `${HIGHLIGHT_ZOOM_MS + 700}ms`,
      `${HIGHLIGHT_ZOOM_MS + 1400}ms`,
    ])
  })

  test("draws no labels without names or while searching", () => {
    const names = ["Vilnius", "Riga", "Tallinn", "Vilnius"]
    const { container, rerender } = render(<EuropeLoader loading={false} highlight={stops} />)
    expect(container.querySelector(".eu-best-label")).toBeNull()
    rerender(<EuropeLoader loading highlight={stops} highlightLabels={names} />)
    expect(container.querySelector(".eu-best-label")).toBeNull()
  })

  test("fades the whole path out over 3 seconds once it has drawn", () => {
    const names = ["Vilnius", "Riga", "Tallinn", "Vilnius"]
    const { container } = render(
      <EuropeLoader loading={false} highlight={stops} highlightLabels={names} />
    )
    const drawn = HIGHLIGHT_ZOOM_MS + 3 * 700
    for (const id of ["cheapest-path", "cheapest-labels"]) {
      const group = container.querySelector(`[data-testid='${id}']`) as HTMLElement
      expect(group).toHaveClass("eu-best-out")
      expect(group.style.getPropertyValue("--out-delay")).toBe(`${drawn}ms`)
      expect(group.style.getPropertyValue("--out-ms")).toBe("3000ms")
    }
  })

  test("is hidden while searching", () => {
    const { container } = render(<EuropeLoader loading highlight={stops} />)
    expect(container.querySelector("[data-testid='cheapest-path']")).toBeNull()
  })

  test("draws nothing without a highlight or with a single stop", () => {
    const { container, rerender } = render(<EuropeLoader loading={false} />)
    expect(container.querySelector("[data-testid='cheapest-path']")).toBeNull()
    rerender(<EuropeLoader loading={false} highlight={[stops[0]]} />)
    expect(container.querySelector("[data-testid='cheapest-path']")).toBeNull()
  })

  test("skips zero-length hops", () => {
    const { container } = render(
      <EuropeLoader loading={false} highlight={[stops[0], stops[0], stops[1]]} />
    )
    expect(container.querySelectorAll("[data-testid='cheapest-path'] > g")).toHaveLength(1)
  })
})
