"use client"

import dynamic from "next/dynamic"
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react"

import { resolvePlaces, isInMapRegion, type Departure } from "@/lib/europe-places"
import {
  ROUTE_FADE_MS,
  HOLD_MS,
  TRAIL,
  arcPath,
  planCascadeFrom,
  arrivalMs,
  frontierCities,
  planRound,
  highlightTimeline,
  roundDurationMs,
  type LonLat,
  type PlannedRoute,
} from "@/lib/europe-route-wave"
import { cn } from "@/lib/utils"

// Leaflet touches `window`, so the Leaflet map is client-only.
const EuropeOsmMap = dynamic(() => import("@/components/europe-osm-map"), {
  ssr: false,
})

// How long the routes take to fade when the search ends.
const FADE_MS = 350
// Pause between two rounds of routes while the search is still running.
const ROUND_PAUSE_MS = 200
// Each wave after the first branches less, so the endless cascade stays light.
const CONTINUATION_BRANCHING = [2, 1] as const
const MAX_REAL_DESTINATIONS = 8

// Moving light, built from stacked dashes sharing one head: a trail that fades
// out gradually, a faint halo (a cheap stand-in for a blur filter, which would
// repaint every frame), a ruby head and a silver-white core.
const TRAIL_LAYERS = [
  { len: TRAIL, opacity: 0.1, width: 1.25 },
  { len: TRAIL * 0.72, opacity: 0.16, width: 1.25 },
  { len: TRAIL * 0.46, opacity: 0.26, width: 1.35 },
  { len: TRAIL * 0.24, opacity: 0.42, width: 1.5 },
] as const
const HEAD_LAYERS = [
  { len: 0.06, className: "eu-ruby", width: 3.4, opacity: 0.16 },
  { len: 0.05, className: "eu-ruby", width: 1.7, opacity: 1 },
  { len: 0.022, className: "eu-silver", width: 1, opacity: 1 },
] as const

// Neon halo: wider, fainter strokes under the line. Stacked strokes instead of
// an SVG blur filter, which would repaint every frame.
const GLOW_LAYERS = [
  { width: 7, opacity: 0.12 },
  { width: 4, opacity: 0.25 },
]

const CSS = `
.eu-root { --eu-route: #ffffff; --eu-ruby: var(--eu-route); --eu-silver: var(--eu-route) }
@keyframes eu-draw { from { stroke-dashoffset: 1 } to { stroke-dashoffset: 0 } }
@keyframes eu-beam { 0% { stroke-dashoffset: var(--len); opacity: 0 } 6% { opacity: 1 } 90% { opacity: 1 } 100% { stroke-dashoffset: calc(var(--len) - ${1 + TRAIL}); opacity: 0 } }
@keyframes eu-fade { from { opacity: 1 } to { opacity: 0 } }
@keyframes eu-arrive { 0% { opacity: 0; transform: scale(.7) } 20% { opacity: .95 } 100% { opacity: 0; transform: scale(3) } }
@keyframes eu-ripple { 0% { opacity: .9; transform: scale(.4) } 100% { opacity: 0; transform: scale(4) } }
@keyframes eu-blink { 50% { opacity: .35 } }
@keyframes eu-best-out { from { opacity: 1 } to { opacity: 0 } }
.eu-best-out { animation: eu-best-out var(--out-ms) ease-in-out var(--out-delay) forwards }
@keyframes eu-label-in { from { opacity: 0 } to { opacity: 1 } }
.eu-best-stop { opacity: 0; animation: eu-label-in 500ms ease-out var(--delay) forwards }
.eu-best-dot { fill: var(--eu-route) }
.eu-best-label { fill: var(--eu-route); stroke: rgb(0 0 0 / .6); stroke-width: 3px; paint-order: stroke; stroke-linejoin: round; font-size: 13px; font-weight: 600; text-anchor: middle }
@keyframes eu-best-pulse { 0%, 100% { opacity: .65 } 50% { opacity: 1 } }
.eu-best { stroke: var(--eu-route); stroke-dasharray: 1; stroke-dashoffset: 1; animation: eu-draw var(--draw) ease-out var(--delay) forwards }
.eu-best-glow { animation: eu-draw var(--draw) ease-out var(--delay) forwards, eu-best-pulse 2s ease-in-out calc(var(--delay) + var(--draw)) infinite }
.eu-line { stroke: var(--eu-route) }
.eu-ruby { stroke: var(--eu-ruby) }
.eu-silver { stroke: var(--eu-silver) }
.eu-draw, .eu-glow { stroke-dasharray: 1; stroke-dashoffset: 1; animation: eu-draw var(--draw) linear var(--delay) forwards }
.eu-beam { stroke-linecap: butt; stroke-dasharray: var(--len) 3; stroke-dashoffset: var(--len); opacity: 0; animation: eu-beam var(--beam) linear var(--delay) forwards }
.eu-life { animation: eu-fade ${ROUTE_FADE_MS}ms ease-in var(--fade-delay) forwards }
.eu-arrive { fill: var(--eu-ruby); transform-box: fill-box; transform-origin: center; opacity: 0; animation: eu-arrive 450ms ease-out var(--arrive-delay) both }
.eu-fade-out { animation: eu-fade ${FADE_MS}ms ease-in-out forwards }
.eu-ripple { transform-box: fill-box; transform-origin: center; opacity: 0; animation: eu-ripple 1.1s ease-out infinite }
.eu-label { animation: eu-blink .8s ease-in-out infinite }
@media (prefers-reduced-motion: reduce) {
  .eu-draw, .eu-glow, .eu-best { animation: none; stroke-dashoffset: 0 }
  .eu-best-glow { animation: none }
  .eu-best-stop { animation: none; opacity: 1 }
  .eu-beam, .eu-arrive { display: none }
  .eu-life, .eu-ripple, .eu-label { animation: none }
  .eu-fade-out { animation: none; opacity: 0 }
  .eu-ripple { opacity: .5; transform: scale(2) }
}
`

// Glowing white path of the cheapest trip: wide faint strokes under a bright core.
const BEST_GLOW_LAYERS = [
  { width: 14, opacity: 0.12 },
  { width: 9, opacity: 0.2 },
  { width: 5, opacity: 0.38 },
] as const
// Share of the screen kept empty around the path, so the zoom stays loose.
const PATH_INSET = 0.22

/**
 * One labelled stop per distinct place: a round trip ends where it began, and
 * a stop must not be written twice. `index` is the first visit, which times the
 * label to the moment the path arrives.
 */
function uniqueStops(points: readonly LonLat[], names: readonly string[]) {
  const seen = new Set<string>()
  const stops: { at: LonLat; name: string; index: number }[] = []
  points.forEach((at, index) => {
    const key = `${at[0]},${at[1]}`
    const name = names[index]
    if (seen.has(key) || !name) return
    seen.add(key)
    stops.push({ at, name, index })
  })
  return stops
}

// Searching lines are drawn this many times thicker than the base widths below.
const LINE_THICKNESS = 1.8
const MIN_LINE_OPACITY = 0.3

/**
 * Pseudo-random brightness of a line in [MIN_LINE_OPACITY, 1], derived from its
 * key: lines look randomly dimmed, yet the same line always gets the same value
 * (no Math.random, so renders and tests stay deterministic).
 */
export function lineOpacity(key: string) {
  let h = 2166136261
  for (let i = 0; i < key.length; i++) {
    h ^= key.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  const unit = (h >>> 0) / 4294967295
  return Number((MIN_LINE_OPACITY + unit * (1 - MIN_LINE_OPACITY)).toFixed(2))
}

type Round = { id: number; routes: PlannedRoute[] }

/** Id of the round whose lines converge on the highlighted path; it is not faded as a finished search. */
const CONVERGE_ID = -1
// How many recent line origins are remembered for the convergence.
const RECENT_ORIGINS = 16
// Share of the zoom the converging lines take to draw; the rest is the hold before they fade.
const CONVERGE_DRAW_SHARE = 0.7
const CONVERGE_STAGGER_SHARE = 0.25

/**
 * Re-targets lines onto the stops of the highlighted path, handing the stops
 * out in turn so each receives the same number of lines (a line never ends
 * where it starts). Timed to finish as the map zoom does.
 */
export function planConvergence(
  origins: readonly LonLat[],
  stops: readonly LonLat[],
  zoomMs: number
): PlannedRoute[] {
  const same = (a: LonLat, b: LonLat) => a[0] === b[0] && a[1] === b[1]
  const targets = stops.filter((s, i) => stops.findIndex((o) => same(o, s)) === i)
  if (targets.length === 0) return []
  const beamMs = zoomMs * CONVERGE_DRAW_SHARE
  const stagger = origins.length > 1 ? (zoomMs * CONVERGE_STAGGER_SHARE) / (origins.length - 1) : 0
  const routes: PlannedRoute[] = []
  let turn = 0
  origins.forEach((from, i) => {
    for (let k = 0; k < targets.length; k++) {
      const to = targets[(turn + k) % targets.length]
      if (same(from, to)) continue
      turn = (turn + k + 1) % targets.length
      routes.push({
        key: `converge:${i}>${to[0]},${to[1]}`,
        from,
        to,
        startMs: i * stagger,
        beamMs,
        drawMs: beamMs / (1 + TRAIL),
      })
      return
    }
  })
  return routes
}

export function EuropeLoader({
  departure,
  loading = true,
  satellite = true,
  ...props
}: {
  /**
   * Departure city. A capital is matched by name; any other city with
   * coordinates inside the map is added as an extra point.
   */
  departure?: Departure | null
  /** Animate the routes. When false the map stays visible but still. */
  loading?: boolean
  /** Show satellite imagery (default); false shows only country outlines. */
  satellite?: boolean
  /**
   * Real destinations of the search results. When omitted the animation shows
   * decorative example routes between European capitals; they do not
   * represent availability.
   */
  destinations?: readonly { lon: number; lat: number }[]
  /**
   * Ordered stops of the cheapest trip, as [lon, lat]. Drawn as a glowing white
   * path once the search has finished.
   */
  highlight?: readonly LonLat[]
  /** City names for `highlight`, same order; written next to each stop. */
  highlightLabels?: readonly string[]
  /** Fixed length of the whole highlight showcase (zoom, draw, fade); default: derived from the path. */
  highlightDurationMs?: number
  /** Called with true while the map zooms between regions, false once it settles. */
  onFlight?: (flying: boolean) => void
  label?: string
  className?: string
}) {
  const name = departure?.name
  const lon = departure?.lon
  const lat = departure?.lat
  const resolved = useMemo(
    () => resolvePlaces(name === undefined ? null : { name, lon, lat }),
    [name, lon, lat]
  )
  // Remount so the routes restart from a new departure.
  return (
    <EuropeLoaderRoutes
      key={`${name ?? ""}|${lon}|${lat}`}
      resolved={resolved}
      loading={loading}
      satellite={satellite}
      {...props}
    />
  )
}

function EuropeLoaderRoutes({
  resolved,
  loading,
  satellite,
  destinations,
  highlight,
  highlightLabels,
  highlightDurationMs,
  onFlight,
  label = "Searching routes",
  className,
}: {
  resolved: ReturnType<typeof resolvePlaces>
  loading: boolean
  satellite: boolean
  destinations?: readonly { lon: number; lat: number }[]
  highlight?: readonly LonLat[]
  highlightLabels?: readonly string[]
  highlightDurationMs?: number
  onFlight?: (flying: boolean) => void
  label?: string
  className?: string
}) {
  const { places, origin, start } = resolved
  const points = useMemo(
    () => places.map((p): LonLat => [p.lon, p.lat]),
    [places]
  )
  const realDestinations = useMemo(
    () =>
      (destinations ?? [])
        .filter(
          (d) =>
            Number.isFinite(d.lon) && Number.isFinite(d.lat) && isInMapRegion(d.lon, d.lat)
        )
        .slice(0, MAX_REAL_DESTINATIONS)
        .map((d): LonLat => [d.lon, d.lat]),
    [destinations]
  )

  // Once the cheapest path shows, the map zooms onto its region. A path that
  // collapses to one point has no region to zoom to.
  const showPath =
    !loading &&
    highlight !== undefined &&
    highlight.some((p) => p[0] !== highlight[0][0] || p[1] !== highlight[0][1])
  const fit = showPath ? highlight : points

  const timeline = highlightTimeline(highlight ?? [], highlightDurationMs)

  // Once drawn, the whole path (lines, dots, names) fades away slowly.
  const fadeVars = {
    "--out-delay": `${timeline.fadeStartMs}ms`,
    "--out-ms": `${timeline.fadeMs}ms`,
  } as CSSProperties

  // Waves on screen. Decorative routes are endless: each wave continues from the
  // cities the previous one reached, so nothing restarts from the origin. Real
  // destinations are drawn one round at a time.
  const [rounds, setRounds] = useState<Round[]>([])
  const roundCounter = useRef(0)
  // Origins of the most recent lines: they are the ones that converge on the path.
  const recentOrigins = useRef<LonLat[]>([])
  const [converge, setConverge] = useState<Round | null>(null)
  const highlightKey = showPath && highlight ? highlight.map((p) => p.join(",")).join(">") : ""
  const zoomMs = timeline.zoomMs

  useEffect(() => {
    // Search finished: let what is on screen fade out, then drop it.
    if (!loading) {
      const t = setTimeout(() => setRounds([]), FADE_MS)
      return () => clearTimeout(t)
    }

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    const timers = new Set<ReturnType<typeof setTimeout>>()
    const later = (fn: () => void, ms: number) => {
      const t = setTimeout(() => {
        timers.delete(t)
        fn()
      }, ms)
      timers.add(t)
    }
    let frontier: number[] = []

    const add = (id: number, routes: PlannedRoute[]) => {
      recentOrigins.current = [
        ...recentOrigins.current,
        ...routes.map((r) => r.from),
      ].slice(-RECENT_ORIGINS)
      setRounds((current) => [...current, { id, routes }])
    }
    const remove = (id: number) =>
      setRounds((current) => current.filter((r) => r.id !== id))

    const run = () => {
      const id = roundCounter.current++
      if (realDestinations.length > 0) {
        // Real destinations are drawn as given, then repeated.
        const routes = planRound(points[start], realDestinations)
        add(id, routes)
        if (reduced) return
        later(() => {
          remove(id)
          later(run, ROUND_PAUSE_MS)
        }, roundDurationMs(routes))
        return
      }
      const routes =
        frontier.length === 0
          ? planCascadeFrom(points, [start], id)
          : planCascadeFrom(points, frontier, id, CONTINUATION_BRANCHING)
      frontier = frontierCities(routes)
      add(id, routes)
      // Reduced motion: one static set of routes, no cycling.
      if (reduced) return
      later(() => remove(id), roundDurationMs(routes))
      // The next wave leaves as soon as this one's beams have arrived.
      later(run, frontier.length === 0 ? roundDurationMs(routes) : arrivalMs(routes))
    }

    // A new search starts from a clean map, never stacked on leftovers.
    later(() => {
      setRounds([])
      run()
    }, 0)
    return () => timers.forEach(clearTimeout)
  }, [loading, points, start, realDestinations])

  // While the map zooms onto the highlighted path, the searching lines end up at its cities.
  useEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    const stops = highlightKey
      ? highlightKey.split(">").map((p) => p.split(",").map(Number) as unknown as LonLat)
      : []
    const t = setTimeout(() => {
      const origins = recentOrigins.current
      const routes =
        stops.length === 0 || reduced || origins.length === 0
          ? []
          : planConvergence(origins, stops, zoomMs)
      setConverge(routes.length > 0 ? { id: CONVERGE_ID, routes } : null)
    }, 0)
    return () => clearTimeout(t)
  }, [highlightKey, zoomMs])

  return (
    <div
      role={loading ? "status" : "img"}
      aria-live={loading ? "polite" : undefined}
      aria-label={loading ? label : "Map of European capitals"}
      className={cn(
        "eu-root relative isolate min-h-[28rem] w-full overflow-hidden bg-white dark:bg-background",
        className
      )}
    >
      <style>{CSS}</style>
      <EuropeOsmMap fit={fit} fitInset={showPath ? PATH_INSET : undefined} zoomMs={timeline.zoomMs} satellite={satellite} onFlight={onFlight} className="absolute inset-0 z-0 bg-white! dark:bg-background!">
        {({ project, width, height }) => {
          const drawn = (converge ? [...rounds, converge] : rounds).map((round) => ({
            round,
            routes: round.routes.map((r) => {
              const to = project(r.to)
              return { route: r, to, d: arcPath(project(r.from), to) }
            }),
          }))
          // The origin ripple only belongs to the animation: shown while searching
          // and while the last round fades out, hidden otherwise.
          const active = loading || rounds.length > 0
          return (
            <svg
              width={width}
              height={height}
              className="absolute inset-0 text-primary"
              aria-hidden
            >
              {drawn.map(({ round, routes: shown }) => (
                <g
                  key={round.id}
                  className={loading || round.id === CONVERGE_ID ? undefined : "eu-fade-out"}
                  fill="none"
                  strokeLinejoin="round"
                >
                  {shown.map(({ route: r, d }) => {
                    const vars = {
                      "--delay": `${r.startMs}ms`,
                      "--draw": `${r.drawMs}ms`,
                      "--beam": `${r.beamMs}ms`,
                      "--fade-delay": `${r.startMs + r.beamMs + HOLD_MS}ms`,
                    } as CSSProperties
                    return (
                      <g key={r.key} className="eu-life" style={vars}>
                        <g data-testid="search-line" opacity={lineOpacity(`${round.id}|${r.key}`)}>
                        {GLOW_LAYERS.map((l) => (
                          <path
                            key={l.width}
                            d={d}
                            pathLength={1}
                            className="eu-line eu-glow"
                            strokeWidth={l.width * LINE_THICKNESS}
                            strokeOpacity={l.opacity}
                            strokeLinecap="round"
                          />
                        ))}
                        <path
                          d={d}
                          pathLength={1}
                          className="eu-line eu-draw"
                          strokeWidth={1.25 * LINE_THICKNESS}
                          strokeLinecap="round"
                        />
                        {TRAIL_LAYERS.map((l) => (
                          <path
                            key={l.len}
                            d={d}
                            pathLength={1}
                            className="eu-beam eu-ruby"
                            strokeWidth={l.width * LINE_THICKNESS}
                            strokeOpacity={l.opacity}
                            style={{ "--len": l.len } as CSSProperties}
                          />
                        ))}
                        {HEAD_LAYERS.map((l) => (
                          <path
                            key={`${l.len}`}
                            d={d}
                            pathLength={1}
                            className={`eu-beam ${l.className}`}
                            strokeWidth={l.width * LINE_THICKNESS}
                            strokeOpacity={l.opacity}
                            style={{ "--len": l.len } as CSSProperties}
                          />
                        ))}
                        </g>
                      </g>
                    )
                  })}
                </g>
              ))}

              {showPath && highlight && (
                <g
                  key={highlight.map((p) => p.join(",")).join(">")}
                  data-testid="cheapest-path"
                  className="eu-best-out"
                  style={fadeVars}
                  fill="none"
                  strokeLinejoin="round"
                  strokeLinecap="round"
                >
                  {highlight.slice(1).flatMap((to, i) => {
                    const from = highlight[i]
                    if (from[0] === to[0] && from[1] === to[1]) return []
                    const d = arcPath(project(from), project(to))
                    const vars = {
                      "--delay": `${timeline.zoomMs + i * timeline.legMs}ms`,
                      "--draw": `${timeline.legMs}ms`,
                    } as CSSProperties
                    return [
                      <g key={i} style={vars}>
                        {BEST_GLOW_LAYERS.map((l) => (
                          <path
                            key={l.width}
                            d={d}
                            pathLength={1}
                            className="eu-best eu-best-glow"
                            strokeWidth={l.width}
                            strokeOpacity={l.opacity}
                          />
                        ))}
                        <path
                          d={d}
                          pathLength={1}
                          className="eu-best"
                          strokeWidth={2.5}
                        />
                      </g>,
                    ]
                  })}
                </g>
              )}

              {showPath && highlight && highlightLabels && (
                <g
                  key={`stops-${highlight.map((p) => p.join(",")).join(">")}`}
                  data-testid="cheapest-labels"
                  className="eu-best-out"
                  style={fadeVars}
                >
                  {uniqueStops(highlight, highlightLabels).map(({ at, name, index }) => {
                    const [x, y] = project(at)
                    return (
                      <g
                        key={`${at[0]},${at[1]}`}
                        className="eu-best-stop"
                        style={
                          {
                            "--delay": `${timeline.zoomMs + index * timeline.legMs}ms`,
                          } as CSSProperties
                        }
                      >
                        <circle cx={x} cy={y} r={4} className="eu-best-dot" />
                        <text x={x} y={y - 12} className="eu-best-label">
                          {name}
                        </text>
                      </g>
                    )
                  })}
                </g>
              )}

              {active && origin !== null && (
                <g
                  className={loading ? undefined : "eu-fade-out"}
                  fill="none"
                  stroke="var(--eu-route)"
                  strokeWidth={1.5}
                >
                  {[0, 1.1].map((delay) => {
                    const [cx, cy] = project(points[origin])
                    return (
                      <circle
                        key={delay}
                        cx={cx}
                        cy={cy}
                        r={7}
                        className="eu-ripple"
                        style={{ animationDelay: `${delay}s` }}
                      />
                    )
                  })}
                </g>
              )}

              {/* Destination dots light up as the beam arrives. */}
              {drawn.map(({ round, routes: shown }) => (
                <g
                  key={`arrive-${round.id}`}
                  className={loading || round.id === CONVERGE_ID ? undefined : "eu-fade-out"}
                >
                  {shown.map(({ route: r, to }) => (
                    <circle
                      key={r.key}
                      cx={to[0]}
                      cy={to[1]}
                      r={4}
                      className="eu-arrive"
                      style={
                        { "--arrive-delay": `${r.startMs + r.drawMs}ms` } as CSSProperties
                      }
                    />
                  ))}
                </g>
              ))}
            </svg>
          )
        }}
      </EuropeOsmMap>
      {loading && (
        <p className="eu-label absolute inset-x-0 bottom-6 z-[600] mx-auto w-fit rounded-full bg-background/80 px-4 py-1.5 font-mono text-xs uppercase tracking-[0.3em] text-muted-foreground backdrop-blur">
          {label}
        </p>
      )}
    </div>
  )
}
