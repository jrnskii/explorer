"use client"

import dynamic from "next/dynamic"
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react"

import { resolvePlaces, isInMapRegion, type Departure } from "@/lib/europe-places"
import {
  ROUTE_FADE_MS,
  HOLD_MS,
  TRAIL,
  arcPath,
  planCascade,
  planRound,
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
const FADE_MS = 700
// Pause between two rounds of routes while the search is still running.
const ROUND_PAUSE_MS = 400
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
.eu-root { --eu-route: #7fff00; --eu-ruby: var(--eu-route); --eu-silver: var(--eu-route) }
@keyframes eu-draw { from { stroke-dashoffset: 1 } to { stroke-dashoffset: 0 } }
@keyframes eu-beam { 0% { stroke-dashoffset: var(--len); opacity: 0 } 6% { opacity: 1 } 90% { opacity: 1 } 100% { stroke-dashoffset: calc(var(--len) - ${1 + TRAIL}); opacity: 0 } }
@keyframes eu-fade { from { opacity: 1 } to { opacity: 0 } }
@keyframes eu-arrive { 0% { opacity: 0; transform: scale(.7) } 20% { opacity: .95 } 100% { opacity: 0; transform: scale(3) } }
@keyframes eu-ripple { 0% { opacity: .9; transform: scale(.4) } 100% { opacity: 0; transform: scale(4) } }
@keyframes eu-blink { 50% { opacity: .35 } }
.eu-line { stroke: var(--eu-route) }
.eu-ruby { stroke: var(--eu-ruby) }
.eu-silver { stroke: var(--eu-silver) }
.eu-draw, .eu-glow { stroke-dasharray: 1; stroke-dashoffset: 1; animation: eu-draw var(--draw) linear var(--delay) forwards }
.eu-beam { stroke-linecap: butt; stroke-dasharray: var(--len) 3; stroke-dashoffset: var(--len); opacity: 0; animation: eu-beam var(--beam) linear var(--delay) forwards }
.eu-life { animation: eu-fade ${ROUTE_FADE_MS}ms ease-in var(--fade-delay) forwards }
.eu-arrive { fill: var(--eu-ruby); transform-box: fill-box; transform-origin: center; opacity: 0; animation: eu-arrive 900ms ease-out var(--arrive-delay) both }
.eu-fade-out { animation: eu-fade ${FADE_MS}ms ease-in-out forwards }
.eu-ripple { transform-box: fill-box; transform-origin: center; opacity: 0; animation: eu-ripple 2.2s ease-out infinite }
.eu-label { animation: eu-blink 1.6s ease-in-out infinite }
@media (prefers-reduced-motion: reduce) {
  .eu-draw, .eu-glow { animation: none; stroke-dashoffset: 0 }
  .eu-beam, .eu-arrive { display: none }
  .eu-life, .eu-ripple, .eu-label { animation: none }
  .eu-fade-out { animation: none; opacity: 0 }
  .eu-ripple { opacity: .5; transform: scale(2) }
}
`

type Round = { id: number; routes: PlannedRoute[] }

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
  label = "Searching routes",
  className,
}: {
  resolved: ReturnType<typeof resolvePlaces>
  loading: boolean
  satellite: boolean
  destinations?: readonly { lon: number; lat: number }[]
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

  // A single round is on screen at a time, so repeated searches never overlap.
  const [round, setRound] = useState<Round | null>(null)
  const roundCounter = useRef(0)

  useEffect(() => {
    // Search finished: let what is on screen fade out, then drop it.
    if (!loading) {
      const t = setTimeout(() => setRound(null), FADE_MS)
      return () => clearTimeout(t)
    }

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    let timer: ReturnType<typeof setTimeout>

    const run = () => {
      const id = roundCounter.current++
      // Real destinations are drawn as given; only decorative routes cascade on.
      const routes =
        realDestinations.length > 0
          ? planRound(points[start], realDestinations)
          : planCascade(points, start, id)
      setRound({ id, routes })
      // Reduced motion: one static set of routes, no cycling.
      if (reduced) return
      timer = setTimeout(() => {
        setRound(null)
        timer = setTimeout(run, ROUND_PAUSE_MS)
      }, roundDurationMs(routes))
    }

    timer = setTimeout(run, 0)
    return () => clearTimeout(timer)
  }, [loading, points, start, realDestinations])

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
      <EuropeOsmMap fit={points} satellite={satellite} className="absolute inset-0 z-0 bg-white! dark:bg-background!">
        {({ project, width, height }) => {
          const drawn = round?.routes.map((r) => {
            const to = project(r.to)
            return { route: r, to, d: arcPath(project(r.from), to) }
          })
          return (
            <svg
              width={width}
              height={height}
              className="absolute inset-0 text-primary"
              aria-hidden
            >
              {round && drawn && (
                <g
                  key={round.id}
                  className={loading ? undefined : "eu-fade-out"}
                  fill="none"
                  strokeLinejoin="round"
                >
                  {drawn.map(({ route: r, d }) => {
                    const vars = {
                      "--delay": `${r.startMs}ms`,
                      "--draw": `${r.drawMs}ms`,
                      "--beam": `${r.beamMs}ms`,
                      "--fade-delay": `${r.startMs + r.beamMs + HOLD_MS}ms`,
                    } as CSSProperties
                    return (
                      <g key={r.key} className="eu-life" style={vars}>
                        {GLOW_LAYERS.map((l) => (
                          <path
                            key={l.width}
                            d={d}
                            pathLength={1}
                            className="eu-line eu-glow"
                            strokeWidth={l.width}
                            strokeOpacity={l.opacity}
                            strokeLinecap="round"
                          />
                        ))}
                        <path
                          d={d}
                          pathLength={1}
                          className="eu-line eu-draw"
                          strokeWidth={1.25}
                          strokeLinecap="round"
                        />
                        {TRAIL_LAYERS.map((l) => (
                          <path
                            key={l.len}
                            d={d}
                            pathLength={1}
                            className="eu-beam eu-ruby"
                            strokeWidth={l.width}
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
                            strokeWidth={l.width}
                            strokeOpacity={l.opacity}
                            style={{ "--len": l.len } as CSSProperties}
                          />
                        ))}
                      </g>
                    )
                  })}
                </g>
              )}

              {origin !== null && (
                <g fill="none" stroke="currentColor" strokeWidth={1.5}>
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

              <g className="stroke-background" strokeWidth={1.5}>
                {places.map((place, i) => {
                  const [cx, cy] = project(points[i])
                  return (
                    <g key={place.name}>
                      <title>
                        {place.country ? `${place.name}, ${place.country}` : place.name}
                      </title>
                      <circle cx={cx} cy={cy} r={3.5} fill="currentColor" />
                    </g>
                  )
                })}
              </g>

              {/* Destination dots light up as the beam arrives. */}
              {round && drawn && (
                <g
                  key={`arrive-${round.id}`}
                  className={loading ? undefined : "eu-fade-out"}
                >
                  {drawn.map(({ route: r, to }) => (
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
              )}
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
