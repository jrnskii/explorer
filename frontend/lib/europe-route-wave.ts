import { geoDistance } from "d3-geo"

export type LonLat = readonly [number, number]

const distance = (a: LonLat, b: LonLat) => geoDistance([a[0], a[1]], [b[0], b[1]])

/** Number of routes animated per round. */
export const ROUTE_COUNT = 7
/** Delay between the start of consecutive routes; keeps them overlapping. */
export const STAGGER_MS = 170
/** Fraction of the beam's length (relative to the route) that is its trail. */
export const TRAIL = 0.16
/** How long a finished route stays before it starts to fade. */
export const HOLD_MS = 225
/** Duration of the map zoom onto the cheapest path; the path draws after it. */
export const HIGHLIGHT_ZOOM_MS = 1800
/** Time each leg of the cheapest path takes to draw. */
export const HIGHLIGHT_LEG_MS = 700
/** How long the finished cheapest path takes to fade away; the results appear after. */
export const HIGHLIGHT_FADE_MS = 3000
/** Duration of the fade of a finished route. */
export const ROUTE_FADE_MS = 450

const MIN_DISTANCE = 0.07 // radians (~450 km): shorter hops make dull routes.
const MAX_PREFERRED_DISTANCE = 0.35 // radians (~2200 km).
const MIN_BEAM_MS = 550
const SPAN_BEAM_MS = 400

/** Routes started per city, by depth: the origin fans out, then each arrival continues. */
export const CASCADE_BRANCHING = [5, 2, 1] as const

export type PlannedRoute = {
  /** Unique key within a round. */
  key: string
  from: LonLat
  to: LonLat
  /** Delay before the route starts drawing. */
  startMs: number
  /** Time the beam needs to travel the route, trail included. */
  beamMs: number
  /** Time until the beam head reaches the destination (the route is fully drawn). */
  drawMs: number
  /** Indices into the point list; set for cascade routes. */
  fromIndex?: number
  toIndex?: number
}

/**
 * Picks `count` destinations spread around `from` (one per compass sector, so
 * routes fan out instead of overlapping). Deterministic; `phase` rotates the
 * sector boundaries so successive rounds show different cities.
 * Returns indices into `points`, ordered by bearing for a smooth sweep.
 */
export function pickDestinations(
  points: readonly LonLat[],
  from: number,
  count = ROUTE_COUNT,
  phase = 0,
  exclude: ReadonlySet<number> = new Set()
): number[] {
  const origin = points[from]
  if (!origin || count <= 0) return []
  const cosLat = Math.cos((origin[1] * Math.PI) / 180)

  const candidates = points
    .map((p, index) => ({
      index,
      distance: distance(origin, p),
      angle: Math.atan2(p[1] - origin[1], (p[0] - origin[0]) * cosLat),
    }))
    .filter((c) => c.index !== from && !exclude.has(c.index) && c.distance >= MIN_DISTANCE)
  if (candidates.length === 0) return []

  // Lower is better: the longest route that is still reasonable.
  const rank = (distance: number) =>
    distance <= MAX_PREFERRED_DISTANCE
      ? MAX_PREFERRED_DISTANCE - distance
      : distance
  const byRank = [...candidates].sort(
    (a, b) => rank(a.distance) - rank(b.distance) || a.index - b.index
  )

  const sector = (2 * Math.PI) / count
  const sectorOf = (angle: number) => {
    const turn = (((angle + Math.PI + phase * sector * 0.5) % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI)
    return Math.floor(turn / sector)
  }

  const chosen = new Map<number, (typeof candidates)[number]>()
  for (const c of byRank) {
    const s = sectorOf(c.angle)
    if (!chosen.has(s)) chosen.set(s, c)
  }
  const picked = [...chosen.values()].slice(0, count)
  for (const c of byRank) {
    if (picked.length >= count) break
    if (!picked.includes(c)) picked.push(c)
  }
  return picked.sort((a, b) => a.angle - b.angle).map((c) => c.index)
}

function timing(from: LonLat, to: LonLat, longest: number, startMs: number) {
  const beamMs =
    MIN_BEAM_MS + (Math.min(distance(from, to), longest) / longest) * SPAN_BEAM_MS
  return {
    startMs,
    beamMs,
    // The beam head covers 1 route length while its trail leaves the end afterwards.
    drawMs: beamMs / (1 + TRAIL),
  }
}

/** Schedules the routes of one round: staggered starts, longer routes travel longer. */
export function planRound(
  from: LonLat,
  destinations: readonly LonLat[]
): PlannedRoute[] {
  const longest = Math.max(...destinations.map((d) => distance(from, d)), MIN_DISTANCE)
  return destinations.map((to, i) => ({
    key: `${from[0]},${from[1]}>${to[0]},${to[1]}@${i}`,
    from,
    to,
    ...timing(from, to, longest, i * STAGGER_MS),
  }))
}

/**
 * Recursive cascade: routes fan out from `start`; whenever a beam arrives at a
 * city, new routes leave that city (fewer at each depth, never back to a city
 * already on the same path). Child routes start as their parent's beam arrives.
 */
export function planCascade(
  points: readonly LonLat[],
  start: number,
  phase = 0,
  branching: readonly number[] = CASCADE_BRANCHING
): PlannedRoute[] {
  return planCascadeFrom(points, [start], phase, branching)
}

/** Like `planCascade`, but fans out from several cities at once (all starting at 0). */
export function planCascadeFrom(
  points: readonly LonLat[],
  starts: readonly number[],
  phase = 0,
  branching: readonly number[] = CASCADE_BRANCHING
): PlannedRoute[] {
  const routes: PlannedRoute[] = []
  const expand = (
    city: number,
    at: number,
    depth: number,
    path: ReadonlySet<number>
  ) => {
    const count = branching[depth]
    if (!count) return
    const targets = pickDestinations(points, city, count, phase + depth, path)
    targets.forEach((target, i) => {
      const from = points[city]
      const to = points[target]
      const startMs = at + i * (depth === 0 ? STAGGER_MS : STAGGER_MS / 2)
      const route: PlannedRoute = {
        key: `${depth}:${city}>${target}@${routes.length}`,
        from,
        to,
        fromIndex: city,
        toIndex: target,
        ...timing(from, to, MAX_PREFERRED_DISTANCE, startMs),
      }
      routes.push(route)
      expand(target, startMs + route.drawMs + 20, depth + 1, new Set([...path, target]))
    })
  }
  starts.forEach((start, i) => expand(start, i * STAGGER_MS, 0, new Set([start])))
  return routes
}

/** Time until the last route of a plan has fully drawn, i.e. every beam has arrived. */
export function arrivalMs(routes: readonly PlannedRoute[]) {
  return Math.max(0, ...routes.map((r) => r.startMs + r.drawMs))
}

/**
 * Cities the plan ended in: destinations nothing continues from. At most `max`,
 * spread evenly so the next wave still fans out across the map.
 */
export function frontierCities(routes: readonly PlannedRoute[], max = 3): number[] {
  const departed = new Set(routes.map((r) => r.fromIndex))
  const leaves = [
    ...new Set(
      routes.flatMap((r) =>
        r.toIndex !== undefined && !departed.has(r.toIndex) ? [r.toIndex] : []
      )
    ),
  ]
  if (leaves.length <= max) return leaves
  return Array.from({ length: max }, (_, i) => leaves[Math.floor((i * leaves.length) / max)])
}

/** Time from the start of a round until its last route has faded out. */
/**
 * Timeline of the cheapest path: the map zooms, each hop draws in turn, then
 * the whole path fades.
 */
export function highlightTimeline(
  points: readonly LonLat[],
  totalMs?: number
) {
  const hops = Math.max(0, points.length - 1)
  const naturalMs =
    HIGHLIGHT_ZOOM_MS + hops * HIGHLIGHT_LEG_MS + HIGHLIGHT_FADE_MS
  // A fixed total scales every phase proportionally.
  const scale =
    totalMs !== undefined && Number.isFinite(totalMs) && totalMs > 0
      ? totalMs / naturalMs
      : 1
  const zoomMs = HIGHLIGHT_ZOOM_MS * scale
  const legMs = HIGHLIGHT_LEG_MS * scale
  const fadeMs = HIGHLIGHT_FADE_MS * scale
  const fadeStartMs = zoomMs + hops * legMs
  return { zoomMs, legMs, fadeMs, fadeStartMs, endMs: fadeStartMs + fadeMs }
}

export function roundDurationMs(routes: readonly PlannedRoute[]) {
  return Math.max(
    0,
    ...routes.map((r) => r.startMs + r.beamMs + HOLD_MS + ROUTE_FADE_MS)
  )
}

/**
 * Smooth quadratic arc between two pixel positions, bowing consistently
 * towards the top of the screen like a flight path. The arc's height is about
 * `bend / 2` of the distance between the endpoints.
 */
export function arcPath(
  [x0, y0]: readonly [number, number],
  [x1, y1]: readonly [number, number],
  bend = 0.18
): string {
  const dx = x1 - x0
  const dy = y1 - y0
  let nx = -dy
  let ny = dx
  if (ny > 0 || (ny === 0 && nx < 0)) {
    nx = -nx
    ny = -ny
  }
  const cx = (x0 + x1) / 2 + nx * bend
  const cy = (y0 + y1) / 2 + ny * bend
  const f = (n: number) => n.toFixed(1)
  return `M${f(x0)} ${f(y0)}Q${f(cx)} ${f(cy)} ${f(x1)} ${f(y1)}`
}
