import type { City } from "@/components/city-picker"
import type { RoundTripOption } from "@/generated/schema_v1"
import { EU_CAPITALS } from "@/lib/eu-capitals"
import { fold } from "@/lib/europe-cities"
import { isInMapRegion } from "@/lib/europe-places"

export type LonLat = readonly [number, number]

type CitySearch = (query: string, limit?: number) => Promise<City[]>

/**
 * The cheapest option, or null when there is none or when prices are quoted in
 * different currencies (their amounts are not comparable). Ties keep the
 * earliest option.
 */
export function cheapestOption(
  options: readonly RoundTripOption[]
): RoundTripOption | null {
  if (options.length === 0) return null
  const currency = options[0].total_price.currency
  let best: RoundTripOption | null = null
  let bestAmount = Infinity
  for (const option of options) {
    if (option.total_price.currency !== currency) return null
    const amount = Number(option.total_price.amount)
    if (!Number.isFinite(amount)) return null
    if (amount < bestAmount) {
      best = option
      bestAmount = amount
    }
  }
  return best
}

/** City names in travel order, starting at the origin and ending where the last leg ends. */
export function stopNames(option: RoundTripOption): string[] {
  const { path } = option
  if (path.length === 0) return []
  return [path[0].from, ...path.map((leg) => leg.to)]
}

/**
 * Resolves city names to map coordinates: the departure city (when it has
 * coordinates), then EU capitals, then the European city dataset. Resolves to
 * null when any stop is unknown or outside the map, since a partial route
 * would misrepresent the trip.
 */
export async function locateStops(
  names: readonly string[],
  departure: { name: string; lon?: number; lat?: number } | null | undefined,
  search: CitySearch
): Promise<LonLat[] | null> {
  if (names.length === 0) return null
  const cache = new Map<string, LonLat | null>()

  const resolve = async (name: string): Promise<LonLat | null> => {
    const key = fold(name)
    if (cache.has(key)) return cache.get(key) ?? null

    let found: LonLat | null = null
    if (
      departure &&
      fold(departure.name) === key &&
      typeof departure.lon === "number" &&
      typeof departure.lat === "number"
    ) {
      found = [departure.lon, departure.lat]
    }
    if (!found) {
      const capital = EU_CAPITALS.find((c) => fold(c.name) === key)
      if (capital) found = [capital.lon, capital.lat]
    }
    if (!found) {
      const match = (await search(name, 5)).find(
        (c) => fold(c.name) === key && c.lon !== undefined && c.lat !== undefined
      )
      if (match) found = [match.lon as number, match.lat as number]
    }
    if (found && !isInMapRegion(found[0], found[1])) found = null
    cache.set(key, found)
    return found
  }

  const located: LonLat[] = []
  for (const name of names) {
    const point = await resolve(name)
    if (!point) return null
    located.push(point)
  }
  return located
}
