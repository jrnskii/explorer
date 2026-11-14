import { act, render } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest"

import { HIGHLIGHT_ZOOM_MS, highlightTimeline, type LonLat } from "@/lib/europe-route-wave"

import { EuropeLoader, lineOpacity, planConvergence } from "./europe-loader"

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
      parseFloat((p.closest(".eu-life") as HTMLElement).style.getPropertyValue("--delay"))
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

describe("EuropeLoader endless searching", () => {
  beforeEach(() => {
    mockMotion(false)
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  const delays = (container: HTMLElement) =>
    [...container.querySelectorAll(".eu-draw")].map((p) =>
      parseFloat((p.closest(".eu-life") as HTMLElement).style.getPropertyValue("--delay"))
    )

  test("keeps adding routes while searching without ever clearing the map", () => {
    const { container } = render(<EuropeLoader loading />)
    act(() => void vi.advanceTimersByTime(50))
    const seen = new Set(
      [...container.querySelectorAll(".eu-draw")].map((p) => p.getAttribute("d"))
    )
    let sawContinuation = false
    for (let i = 0; i < 40; i++) {
      act(() => void vi.advanceTimersByTime(250))
      const drawn = container.querySelectorAll(".eu-draw")
      expect(drawn.length).toBeGreaterThan(0)
      drawn.forEach((p) => {
        if (!seen.has(p.getAttribute("d"))) sawContinuation = true
      })
      expect(drawn.length).toBeLessThanOrEqual(40)
    }
    expect(sawContinuation).toBe(true)
    expect(delays(container).length).toBeGreaterThan(0)
  })
})

describe("EuropeLoader convergence on the highlighted path", () => {
  beforeEach(() => {
    mockMotion(false)
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  const stops: [number, number][] = [
    [25.28, 54.69],
    [21.01, 52.23],
    [13.4, 52.52],
    [18.07, 59.33],
    [24.1, 56.95],
    [25.28, 54.69],
  ]
  const project = ([lon, lat]: readonly [number, number]) => [lon * 10 + 300, 800 - lat * 10]
  const endOf = (d: string) => {
    const n = d.match(/-?\d+(\.\d+)?/g)!.map(Number)
    return [n[n.length - 2], n[n.length - 1]]
  }
  const converging = (container: HTMLElement) =>
    [...container.querySelectorAll(".eu-draw")].filter((p) => !p.closest(".eu-fade-out"))

  test("while zooming, every searching line ends at a city of the highlighted path, evenly", () => {
    const { container, rerender } = render(<EuropeLoader loading />)
    act(() => void vi.advanceTimersByTime(3000))
    rerender(<EuropeLoader loading={false} highlight={stops} highlightLabels={[]} />)
    act(() => void vi.advanceTimersByTime(50))

    const lines = converging(container)
    expect(lines.length).toBeGreaterThan(0)
    const targets = new Set(stops.map((s) => project(s).map((n) => n.toFixed(1)).join(",")))
    const counts = new Map<string, number>()
    for (const line of lines) {
      const end = endOf(line.getAttribute("d")!).map((n) => n.toFixed(1)).join(",")
      expect(targets.has(end)).toBe(true)
      counts.set(end, (counts.get(end) ?? 0) + 1)
    }
    const values = [...counts.values()]
    expect(Math.max(...values) - Math.min(...values)).toBeLessThanOrEqual(1)
  })

  test("converging lines are drawn during the zoom and fade once it ends", () => {
    const { container, rerender } = render(<EuropeLoader loading />)
    act(() => void vi.advanceTimersByTime(3000))
    rerender(<EuropeLoader loading={false} highlight={stops} highlightDurationMs={5000} />)
    act(() => void vi.advanceTimersByTime(50))
    for (const line of converging(container)) {
      const g = line.closest(".eu-life") as HTMLElement
      const start = parseFloat(g.style.getPropertyValue("--delay"))
      const beam = parseFloat(g.style.getPropertyValue("--beam"))
      expect(start + beam).toBeLessThanOrEqual(highlightTimeline(stops, 5000).zoomMs)
    }
  })

  test("without a highlighted path nothing converges", () => {
    const { container, rerender } = render(<EuropeLoader loading />)
    act(() => void vi.advanceTimersByTime(3000))
    rerender(<EuropeLoader loading={false} />)
    act(() => void vi.advanceTimersByTime(50))
    expect(converging(container)).toHaveLength(0)
  })

  test("reduced motion skips the convergence", () => {
    mockMotion(true)
    const { container, rerender } = render(<EuropeLoader loading />)
    act(() => void vi.advanceTimersByTime(100))
    rerender(<EuropeLoader loading={false} highlight={stops} />)
    act(() => void vi.advanceTimersByTime(50))
    expect(converging(container)).toHaveLength(0)
  })
})

describe("planConvergence", () => {
  const origins: LonLat[] = [[0, 0], [1, 1], [2, 2], [3, 3], [4, 4], [5, 5], [6, 6]]
  const stops: LonLat[] = [[10, 10], [11, 11], [12, 12], [10, 10]]

  test("hands the distinct stops out evenly and never ends a line where it starts", () => {
    const routes = planConvergence(origins, stops, 2000)
    expect(routes).toHaveLength(origins.length)
    const counts = new Map<string, number>()
    routes.forEach((r) => counts.set(r.to.join(","), (counts.get(r.to.join(",")) ?? 0) + 1))
    expect(counts.size).toBe(3)
    expect(Math.max(...counts.values()) - Math.min(...counts.values())).toBeLessThanOrEqual(1)
  })

  test("skips a stop equal to the line's origin and finishes within the zoom", () => {
    const routes = planConvergence([[10, 10]], stops, 2000)
    expect(routes).toHaveLength(1)
    expect(routes[0].to).not.toEqual([10, 10])
    expect(planConvergence(origins, stops, 2000).every((r) => r.startMs + r.beamMs <= 2000)).toBe(true)
    expect(planConvergence(origins, [], 2000)).toEqual([])
  })
})

describe("searching line style", () => {
  beforeEach(() => mockMotion(false))
  afterEach(() => vi.unstubAllGlobals())

  test("lineOpacity is deterministic, within bounds and varies between lines", () => {
    const values = Array.from({ length: 50 }, (_, i) => lineOpacity(`0|route-${i}`))
    values.forEach((v) => {
      expect(v).toBeGreaterThanOrEqual(0.3)
      expect(v).toBeLessThanOrEqual(1)
    })
    expect(new Set(values).size).toBeGreaterThan(10)
    expect(lineOpacity("0|route-3")).toBe(values[3])
  })

  test("drawn lines are thicker than the base width and dimmed unevenly", () => {
    vi.useFakeTimers()
    const { container } = render(<EuropeLoader loading />)
    act(() => void vi.advanceTimersByTime(50))
    vi.useRealTimers()
    const core = [...container.querySelectorAll(".eu-draw")]
    expect(core.length).toBeGreaterThan(1)
    core.forEach((p) => expect(Number(p.getAttribute("stroke-width"))).toBeGreaterThan(1.25))
    const dims = new Set(
      [...container.querySelectorAll('[data-testid="search-line"]')].map((g) => g.getAttribute("opacity"))
    )
    expect(dims.size).toBeGreaterThan(1)
  })
})
