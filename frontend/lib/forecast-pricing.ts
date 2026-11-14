import type { RoundTripOption, TransportType } from "@/generated/schema_v1"

export type FareQuery = {
  mode: TransportType
  origin: string
  destination: string
  departure_date: string
  origin_country?: string
  destination_country?: string
  travelers?: number
}
export type FareEstimate = {
  price: { amount: string; currency: string }
  model_id: string
  warnings: string[]
}

export async function fetchFareEstimates(queries: FareQuery[], signal?: AbortSignal): Promise<(FareEstimate | null)[]> {
  if (!queries.length) return []
  const response = await fetch("/api/pricing", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ queries }), signal,
  })
  if (!response.ok) throw new Error("Price estimates are unavailable. Please try again.")
  const body: unknown = await response.json()
  if (!body || typeof body !== "object" || !("forecasts" in body) || !Array.isArray(body.forecasts) || body.forecasts.length !== queries.length) {
    throw new Error("Invalid price estimate response.")
  }
  return body.forecasts.map((item: unknown) => {
    if (item === null) return null
    if (!item || typeof item !== "object" || !("price" in item) || !item.price ||
        typeof item.price !== "object" || !("amount" in item.price) || !("currency" in item.price) ||
        typeof item.price.amount !== "string" || !/^\d+\.\d{2}$/.test(item.price.amount) || item.price.currency !== "EUR" ||
        !("model_id" in item) || typeof item.model_id !== "string" ||
        !("warnings" in item) || !Array.isArray(item.warnings) || !item.warnings.every((w: unknown) => typeof w === "string")) {
      throw new Error("Invalid price estimate response.")
    }
    return { price: { amount: item.price.amount, currency: "EUR" }, model_id: item.model_id, warnings: item.warnings }
  })
}

/** Each preview leg is explicitly a separate one-way demo ticket; no bundled fares. */
export function applyFareEstimates(options: RoundTripOption[], estimates: (FareEstimate | null)[]): RoundTripOption[] {
  if (estimates.length !== options.reduce((n, option) => n + option.path.length, 0)) throw new Error("Missing fare estimates.")
  let index = 0
  return options.flatMap((option) => {
    const fares = option.path.map(() => estimates[index++])
    if (fares.some((fare) => fare === null)) return []
    const cents = fares.reduce((sum, fare) => sum + (fare ? BigInt(fare.price.amount.replace(".", "")) : BigInt(0)), BigInt(0))
    const amount = `${cents / BigInt(100)}.${String(cents % BigInt(100)).padStart(2, "0")}`
    return [{ ...option, total_price: { amount, currency: "EUR" } }]
  }).sort((a, b) => Number(a.total_price.amount) - Number(b.total_price.amount))
}
