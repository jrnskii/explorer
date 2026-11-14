import type { RoundTripOption } from "@/generated/schema_v1"
import type { TripInputsValue } from "@/components/trip-inputs"
import { applyFareEstimates, fetchFareEstimates, type FareQuery } from "./forecast-pricing"

const COUNTRIES: Record<string, string> = {
  Vilnius: "LT", Riga: "LV", Tallinn: "EE", Prague: "CZ", Vienna: "AT", Berlin: "DE",
  Amsterdam: "NL", Paris: "FR", Barcelona: "ES", Rome: "IT",
}

export function prepareSamples(options: RoundTripOption[], input: TripInputsValue): RoundTripOption[] {
  if (!input.date || !input.departure) throw new Error("Choose a departure city and date.")
  if (input.flexibleDates) throw new Error("Sample pricing supports fixed dates only. Disable flexible dates to continue.")
  const day = Date.UTC(input.date.getFullYear(), input.date.getMonth(), input.date.getDate())
  const limit = input.returnDate ? Date.UTC(input.returnDate.getFullYear(), input.returnDate.getMonth(), input.returnDate.getDate()) + 86400000 :
    day + Number(input.duration.split("-").at(-1) || 365) * 86400000
  return options.filter((option) => option.path[0]?.from_city.name === input.departure?.name)
    .map((option) => {
      const first = new Date(option.path[0].departure_at)
      const shift = day - Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), first.getUTCDate())
      return { ...option, path: option.path.map((leg) => ({ ...leg,
        departure_at: new Date(Date.parse(leg.departure_at) + shift).toISOString(),
        arrival_at: new Date(Date.parse(leg.arrival_at) + shift).toISOString(),
      })) }
    }).filter((option) => {
      const visits = new Set(option.path.map((leg) => leg.to_city.name))
      const stops = [...visits].filter((city) => city !== input.departure?.name)
      return option.path.every((leg) => input.modes.includes(leg.transport_type)) &&
        Date.parse(option.path[option.path.length - 1].arrival_at) < limit &&
        input.mustVisit.every((city) => visits.has(city.name)) &&
        input.avoid.every((city) => !visits.has(city.name)) &&
        (!input.numberOfCities || stops.length === Number(input.numberOfCities)) &&
        (!input.daysPerCity || option.city_stays.every((stay) => stay.time_spent >= Number(input.daysPerCity) * 86400))
    })
}

export async function priceSamples(options: RoundTripOption[], input: TripInputsValue, signal?: AbortSignal): Promise<RoundTripOption[]> {
  const candidates = prepareSamples(options, input)
  const queries: FareQuery[] = candidates.flatMap((option) => option.path.map((leg) => ({
    mode: leg.transport_type, origin: leg.from_city.name, destination: leg.to_city.name,
    origin_country: COUNTRIES[leg.from_city.name], destination_country: COUNTRIES[leg.to_city.name],
    departure_date: leg.departure_at.slice(0, 10), travelers: input.travelers,
  })))
  const budget = moneyCents(input.budget)
  const estimates = await fetchFareEstimates(queries, signal)
  const priced = applyFareEstimates(candidates, estimates)
  return priced.filter((option) => moneyCents(option.total_price.amount) <= budget)
}

function moneyCents(value: string): bigint {
  if (!/^\d+(?:\.\d{1,2})?$/.test(value)) throw new Error("Enter a valid EUR budget with at most two decimal places.")
  const [whole, fraction = ""] = value.split(".")
  return BigInt(whole) * BigInt(100) + BigInt(fraction.padEnd(2, "0"))
}
