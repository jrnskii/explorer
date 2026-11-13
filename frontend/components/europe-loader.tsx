"use client"

import { geoDistance, geoInterpolate } from "d3-geo"
import dynamic from "next/dynamic"
import { useEffect, useMemo, useState } from "react"

import type { LonLat, Projector } from "@/components/europe-osm-map"
import { resolvePlaces, type Departure, type Place } from "@/lib/europe-places"
import { nextHub } from "@/lib/europe-route-walk"
import { cn } from "@/lib/utils"

// Leaflet touches `window`, so the Leaflet map is client-only.
const EuropeOsmMap = dynamic(() => import("@/components/europe-osm-map"), {
  ssr: false,
})

// A hop takes MIN_HOP_MS plus a share of SPAN_HOP_MS proportional to its length.
const SPEED = 1.5
const MIN_HOP_MS = 500 / SPEED
const SPAN_HOP_MS = 2000 / SPEED
// How long a finished connection takes to fade away.
const FADE_MS = 1400

type Link = { from: number; to: number; ms: number }
// A hop: the main connection to the next hub plus connections to every other place.
type Hop = { id: number; from: number; main: Link; links: Link[] }

type Graph = { points: [number, number][]; maxDist: number }

function buildGraph(places: readonly Place[]): Graph {
  const points = places.map((p): [number, number] => [p.lon, p.lat])
  const maxDist = Math.max(...points.flatMap((a) => points.map((b) => geoDistance(a, b))))
  return { points, maxDist }
}

const link = (g: Graph, from: number, to: number): Link => ({
  from,
  to,
  // Constant travel speed: longer routes take longer.
  ms: MIN_HOP_MS + (geoDistance(g.points[from], g.points[to]) / g.maxDist) * SPAN_HOP_MS,
})

// The main connection goes to the farthest place not yet visited.
function planHop(g: Graph, id: number, from: number, visited: ReadonlySet<number>) {
  const step = nextHub(g.points, from, visited, geoDistance)
  const hop: Hop = {
    id,
    from,
    main: link(g, from, step.next),
    links: g.points.flatMap((_, i) =>
      i === from || i === step.next ? [] : [link(g, from, i)]
    ),
  }
  return { hop, visited: step.visited }
}

// Great-circle route sampled into a polyline in map pixel space.
const ROUTE_STEPS = 32
function routePath(g: Graph, { from, to }: Link, project: Projector) {
  const along = geoInterpolate(g.points[from], g.points[to])
  let d = ""
  for (let k = 0; k <= ROUTE_STEPS; k++) {
    const [x, y] = project(along(k / ROUTE_STEPS) as LonLat)
    d += `${k ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`
  }
  return d
}

const CSS = `
@keyframes eu-draw { from { stroke-dashoffset: 1 } to { stroke-dashoffset: 0 } }
@keyframes eu-fade { from { opacity: 1 } to { opacity: 0 } }
@keyframes eu-ripple { 0% { opacity: .9; transform: scale(.4) } 100% { opacity: 0; transform: scale(4) } }
@keyframes eu-blink { 50% { opacity: .35 } }
.eu-edge { stroke-dasharray: 1; stroke-dashoffset: 1; animation-name: eu-draw; animation-timing-function: linear; animation-fill-mode: forwards }
.eu-fade-out { animation: eu-fade ${FADE_MS}ms ease-in-out forwards }
.eu-ripple { transform-box: fill-box; transform-origin: center; opacity: 0; animation: eu-ripple 2.2s ease-out infinite }
.eu-label { animation: eu-blink 1.6s ease-in-out infinite }
@media (prefers-reduced-motion: reduce) {
  .eu-edge { animation: none; stroke-dashoffset: 0 }
  .eu-fade-out, .eu-ripple, .eu-label { animation: none }
  .eu-fade-out { opacity: 0 }
  .eu-ripple { opacity: .5; transform: scale(2) }
}
`

export function EuropeLoader({
  departure,
  loading = true,
  ...props
}: {
  /**
   * Departure city. A capital is matched by name; any other city with
   * coordinates inside the map is added as an extra point.
   */
  departure?: Departure | null
  /** Animate the connections. When false the map stays visible but still. */
  loading?: boolean
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
  // Remount so the walk restarts from a new departure or when loading toggles.
  return (
    <EuropeLoaderWalk
      key={`${name ?? ""}|${lon}|${lat}|${loading}`}
      resolved={resolved}
      loading={loading}
      {...props}
    />
  )
}

function EuropeLoaderWalk({
  resolved,
  loading,
  label = "Searching routes",
  className,
}: {
  resolved: ReturnType<typeof resolvePlaces>
  loading: boolean
  label?: string
  className?: string
}) {
  const { places, origin, start } = resolved
  const graph = useMemo(() => buildGraph(places), [places])
  const [first] = useState(() => planHop(graph, 0, start, new Set()))
  // Every hop still on screen; all but the latest are fading out.
  const [hops, setHops] = useState<Hop[]>(loading ? [first.hop] : [])
  const current = hops[hops.length - 1]

  useEffect(() => {
    if (!loading) return
    // The walk lives in the effect so state updaters stay pure (Strict Mode).
    const timers = new Set<ReturnType<typeof setTimeout>>()
    const later = (fn: () => void, ms: number) => {
      const t = setTimeout(() => {
        timers.delete(t)
        fn()
      }, ms)
      timers.add(t)
    }

    let hop = first.hop
    let visited: ReadonlySet<number> = first.visited

    // When the main connection arrives, change direction: new connections
    // leave the reached capital while the previous ones fade away.
    const advance = () => {
      const finished = hop
      const plan = planHop(graph, finished.id + 1, finished.main.to, visited)
      hop = plan.hop
      visited = plan.visited
      setHops((hs) => [...hs, plan.hop])
      later(() => setHops((hs) => hs.filter((h) => h.id !== finished.id)), FADE_MS)
      later(advance, plan.hop.main.ms)
    }

    later(advance, hop.main.ms)
    return () => timers.forEach(clearTimeout)
  }, [graph, first, loading])

  return (
    <div
      role={loading ? "status" : "img"}
      aria-live={loading ? "polite" : undefined}
      aria-label={loading ? label : "Map of European capitals"}
      className={cn(
        "relative isolate min-h-[28rem] w-full overflow-hidden bg-background",
        className
      )}
    >
      <style>{CSS}</style>
      <EuropeOsmMap fit={graph.points} className="absolute inset-0 z-0 bg-background">
        {({ project, width, height }) => (
          <svg
            width={width}
            height={height}
            className="absolute inset-0 text-primary"
            aria-hidden
          >
            {hops.map((h) => (
              <g
                key={h.id}
                className={h.id === current?.id ? undefined : "eu-fade-out"}
                fill="none"
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                {h.links.map((l) => (
                  <path
                    key={l.to}
                    d={routePath(graph, l, project)}
                    pathLength={1}
                    className="eu-edge"
                    strokeWidth={1}
                    strokeOpacity={0.45}
                    style={{ animationDuration: `${l.ms}ms` }}
                  />
                ))}
                <path
                  d={routePath(graph, h.main, project)}
                  pathLength={1}
                  className="eu-edge"
                  strokeWidth={2}
                  strokeOpacity={0.95}
                  style={{ animationDuration: `${h.main.ms}ms` }}
                />
              </g>
            ))}

            {origin !== null && (
              <g fill="none" stroke="currentColor" strokeWidth={1.5}>
                {[0, 1.1].map((delay) => (
                  <circle
                    key={delay}
                    cx={project(graph.points[origin])[0]}
                    cy={project(graph.points[origin])[1]}
                    r={7}
                    className="eu-ripple"
                    style={{ animationDelay: `${delay}s` }}
                  />
                ))}
              </g>
            )}

            <g className="stroke-background" strokeWidth={1.5}>
              {places.map((place, i) => {
                const [cx, cy] = project(graph.points[i])
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
          </svg>
        )}
      </EuropeOsmMap>
      {loading && (
        <p className="eu-label absolute inset-x-0 bottom-6 z-[600] mx-auto w-fit rounded-full bg-background/80 px-4 py-1.5 font-mono text-xs uppercase tracking-[0.3em] text-muted-foreground backdrop-blur">
          {label}
        </p>
      )}
    </div>
  )
}
