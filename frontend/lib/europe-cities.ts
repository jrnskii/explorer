import type { City } from "@/components/city-picker"

// [geonameId, name, ISO country code, lat, lon], most populous first.
type Row = readonly [number, string, string, number, number]

type Index = { cities: City[]; folded: string[] }

let index: Promise<Index> | null = null

/** Lowercases and strips diacritics so "munchen" matches "München". */
export function fold(text: string) {
  return text
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{M}+/gu, "")
    .replace(/ß/g, "ss")
    .replace(/ø/g, "o")
    .replace(/đ/g, "d")
    .replace(/ł/g, "l")
    .trim()
}

// The dataset (GeoNames, CC BY 4.0) is a lazy chunk, loaded on first search.
function loadIndex(): Promise<Index> {
  index ??= import("./data/europe-cities.json").then((mod) => {
    const rows = mod.default as unknown as Row[]
    const countries = new Intl.DisplayNames(["en"], { type: "region" })
    const cities = rows.map(([id, name, cc, lat, lon]): City => ({
      id: `gn-${id}`,
      name,
      country: countries.of(cc) ?? cc,
      lat,
      lon,
    }))
    return { cities, folded: cities.map((c) => fold(c.name)) }
  })
  return index
}

/**
 * Searches European cities (population >= 15,000) by name, ignoring case and
 * diacritics. Better matches come first (exact, prefix, word prefix, substring);
 * ties keep the dataset order, i.e. most populous first.
 */
export async function searchEuropeCities(query: string, limit = 8): Promise<City[]> {
  const q = fold(query)
  if (!q || limit <= 0) return []
  const { cities, folded } = await loadIndex()

  const buckets: City[][] = [[], [], [], []]
  for (let i = 0; i < cities.length; i++) {
    const name = folded[i]
    const at = name.indexOf(q)
    if (at === -1) continue
    const rank =
      name === q ? 0 : at === 0 ? 1 : /[\s\-'’.]/.test(name[at - 1]) ? 2 : 3
    buckets[rank].push(cities[i])
    // Exact and prefix matches are the best we can get; stop once they fill the list.
    if (buckets[0].length + buckets[1].length >= limit) break
  }
  return buckets.flat().slice(0, limit)
}

/**
 * Finds the city called `name` in the country with ISO code `countryCode`.
 * Resolves to null when it is not in the dataset (e.g. non-European countries).
 */
export async function findEuropeCity(
  name: string,
  countryCode: string
): Promise<City | null> {
  const country = new Intl.DisplayNames(["en"], { type: "region" }).of(
    countryCode.toUpperCase()
  )
  const q = fold(name)
  if (!q || !country) return null
  const { cities, folded } = await loadIndex()
  const i = cities.findIndex((c, n) => folded[n] === q && c.country === country)
  return i === -1 ? null : cities[i]
}

/** The most populous European cities, shown before the user types. */
export async function popularEuropeCities(limit = 8): Promise<City[]> {
  return (await loadIndex()).cities.slice(0, limit)
}
