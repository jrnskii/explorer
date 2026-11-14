export type Point = [number, number]

const euclidean = (a: Point, b: Point) => Math.hypot(a[0] - b[0], a[1] - b[1])

/**
 * Picks the next hub of the loader animation: the unvisited point farthest
 * from `current` (Euclidean by default; pass e.g. d3-geo's `geoDistance` for lon/lat). When every point has been visited the walk restarts, so the
 * sequence is infinite. Returns the chosen index and the updated visited set.
 */
export function nextHub(
  points: readonly Point[],
  current: number,
  visited: ReadonlySet<number>,
  distance: (a: Point, b: Point) => number = euclidean
): { next: number; visited: Set<number> } {
  if (points.length < 2) return { next: current, visited: new Set([current]) }

  let seen = new Set(visited)
  seen.add(current)
  if (seen.size >= points.length) seen = new Set([current])

  let next = -1
  let best = -1
  points.forEach((p, i) => {
    if (seen.has(i)) return
    const d = distance(points[current], p)
    if (d > best) {
      best = d
      next = i
    }
  })
  return { next, visited: seen }
}
