import { geoCentroid, geoDistance } from "d3-geo"

import { EU_CAPITALS } from "@/lib/eu-capitals"

export type Place = {
  name: string
  country?: string
  lon: number
  lat: number
}

export type Departure = {
  name: string
  lon?: number
  lat?: number
}

export type Places = {
  /** The capitals, followed by the departure city when it is not a capital. */
  places: readonly Place[]
  /** Index of the departure city in `places`; null when it cannot be shown. */
  origin: number | null
  /** Index the connections start from (the departure, else the central capital). */
  start: number
}

/** Cities outside this window would only distort the Europe-wide map. */
export const MAP_REGION = { west: -25, south: 30, east: 45, north: 72 } as const

export function isInMapRegion(lon: number, lat: number) {
  return (
    lon >= MAP_REGION.west &&
    lon <= MAP_REGION.east &&
    lat >= MAP_REGION.south &&
    lat <= MAP_REGION.north
  )
}

const EARTH_RADIUS_KM = 6371
const SAME_CITY_KM = 15

const CAPITAL_PLACES: readonly Place[] = EU_CAPITALS

function centralIndex(places: readonly Place[]) {
  const centre = geoCentroid({
    type: "MultiPoint",
    coordinates: places.map((p): [number, number] => [p.lon, p.lat]),
  })
  const dist = (p: Place) => geoDistance([p.lon, p.lat], centre)
  return places.reduce((best, p, i) => (dist(p) < dist(places[best]) ? i : best), 0)
}

const CENTRAL_START = centralIndex(CAPITAL_PLACES)

/**
 * Resolves the places shown on the map for a departure city: a capital is
 * matched by name (case-insensitive); any other city with coordinates inside
 * the map region is added as an extra point.
 */
export function resolvePlaces(departure?: Departure | null): Places {
  const wanted = departure?.name.trim().toLowerCase()
  if (!departure || !wanted) {
    return { places: CAPITAL_PLACES, origin: null, start: CENTRAL_START }
  }

  const capital = CAPITAL_PLACES.findIndex((c) => c.name.toLowerCase() === wanted)
  if (capital !== -1) {
    return { places: CAPITAL_PLACES, origin: capital, start: capital }
  }

  const { lon, lat } = departure
  // Data sources name capitals differently ("City of Brussels"); a city that
  // sits on a capital is that capital, not a second dot beside it.
  if (typeof lon === "number" && typeof lat === "number") {
    const near = CAPITAL_PLACES.findIndex(
      (c) => geoDistance([c.lon, c.lat], [lon, lat]) * EARTH_RADIUS_KM < SAME_CITY_KM
    )
    if (near !== -1) return { places: CAPITAL_PLACES, origin: near, start: near }
  }
  if (
    typeof lon === "number" &&
    typeof lat === "number" &&
    Number.isFinite(lon) &&
    Number.isFinite(lat) &&
    isInMapRegion(lon, lat)
  ) {
    const index = CAPITAL_PLACES.length
    return {
      places: [...CAPITAL_PLACES, { name: departure.name, lon, lat }],
      origin: index,
      start: index,
    }
  }

  return { places: CAPITAL_PLACES, origin: null, start: CENTRAL_START }
}
