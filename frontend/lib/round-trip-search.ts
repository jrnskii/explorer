export type EstimatedRoute = {
  rank: number
  cities: { id: string; name: string }[]
  departure_date: string
  return_date: string
  total_price: { amount: string; currency: string }
  schedule_source: string
}

import type { TripInputsValue } from "@/components/trip-inputs"
import type { City } from "@/components/city-picker"
import type { RoundTripOption, RoundTripSearchInput } from "@/generated/schema_v1"

export const ROUND_TRIP_QUERY = `query RoundTripOptions($input: RoundTripSearchInput!) {
  round_trip_options(input: $input) {
    total_price { amount currency }
    stay_fit
    city_stays { city time_spent target_time attractiveness }
    path {
      from to departure_at arrival_at time_in_travel transport_type
      from_city { id name latitude longitude }
      to_city { id name latitude longitude }
    }
  }
}`

function cityId(city: City): string {
  if (!/^gn-\d+$/.test(city.id)) throw new Error("Choose a city from autocomplete.")
  return city.id
}

function localTimestamp(date: Date): string {
  // Preserve the selected calendar day for the provider's date-only searches.
  const offset = -date.getTimezoneOffset()
  const wallTime = new Date(date.getTime() + offset * 60000).toISOString().slice(0, 19)
  const hours = String(Math.floor(Math.abs(offset) / 60)).padStart(2, "0")
  const minutes = String(Math.abs(offset) % 60).padStart(2, "0")
  return `${wallTime}${offset >= 0 ? "+" : "-"}${hours}:${minutes}`
}

export function toRoundTripInput(value: TripInputsValue): RoundTripSearchInput {
  if (!value.departure || !value.date || !Number.isFinite(value.date.getTime())) throw new Error("Choose a departure city and date.")
  if (value.travelers !== 1) throw new Error("The search API currently supports one adult.")
  if (value.daysPerCity) throw new Error("The search API does not support minimum stay filters yet. Clear this filter to search.")
  if (!/^\d+(?:-\d+)?$/.test(value.duration)) throw new Error("Choose a trip duration.")
  const days = value.duration.split("-").map(Number)
  const min = days.length === 2 ? days[0] : 0
  const max = days[days.length - 1]
  if (max < 1 || max > 366 || min > max) throw new Error("Choose a duration of 1–366 days.")
  const departure = new Date(value.date)
  departure.setHours(0, 0, 0, 0)
  const end = new Date(departure)
  end.setDate(end.getDate() + max)
  if (value.returnDate) {
    if (!Number.isFinite(value.returnDate.getTime())) throw new Error("Choose a valid return date.")
    const returnEnd = new Date(value.returnDate)
    returnEnd.setHours(23, 59, 59, 0)
    if (returnEnd < end) end.setTime(returnEnd.getTime())
  }
  const start = new Date(departure)
  start.setDate(start.getDate() + min)
  if (end <= start) throw new Error("The return window must follow departure and the minimum duration.")
  const seconds = (end.getTime() - departure.getTime()) / 1000
  return {
    departure_city: cityId(value.departure),
    departure_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    departure_date: localTimestamp(departure),
    desired_arrival_date: localTimestamp(end),
    time_tolerance: Math.floor((end.getTime() - start.getTime()) / 60000),
    max_trip_duration: seconds,
    mandatory_cities: value.mustVisit.map(cityId),
    excluded_cities: value.avoid.map(cityId),
    transport_types: value.modes,
  }
}

export async function searchRoundTrips(value: TripInputsValue, signal?: AbortSignal, onNotice?: (notice: string, priceStatuses: string[], overBudget: boolean[], estimates: EstimatedRoute[], ranks: number[]) => void): Promise<RoundTripOption[]> {
  const input = toRoundTripInput(value)
  const response = await fetch("/api/round-trip", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input }), signal,
  })
  const payload: unknown = await response.json()
  if (!isObject(payload)) throw new Error("The search API returned an invalid response.")
  const errors = Array.isArray(payload.errors) ? payload.errors : []
  if (!response.ok || errors.length) {
    const message = typeof payload.error === "string" ? payload.error :
      isObject(errors[0]) && typeof errors[0].message === "string" ? errors[0].message :
      "Trip search is unavailable. Please try again."
    throw new Error(message)
  }
  const options = isObject(payload.data) ? payload.data.round_trip_options : undefined
  if (!Array.isArray(options) || !options.every(isRoundTripOption)) throw new Error("The search API returned an invalid response.")
  const metadata = isObject(payload.extensions) ? payload.extensions : {}
  const notices: string[] = []
  if (Array.isArray(metadata.unavailable_transport_types) && metadata.unavailable_transport_types.includes("PLANES")) {
    notices.push("Flight schedules are not included in the current transport data.")
  }
  if (metadata.results_limited === true || Array.isArray(metadata.truncation_reasons) && metadata.truncation_reasons.length) {
    notices.push("The search reached a result or exploration limit. Narrow the dates or transport modes for a more focused search.")
  }
  if (metadata.price_status === "unavailable") {
    notices.push("Scrappa/Omio could not verify the best opportunity or its available fallback. All shown prices remain estimates.")
  }
  if (metadata.price_status === "over_budget") {
    notices.push("The checked option exceeds your budget and is shown below for comparison.")
  }
  const priceStatuses = Array.isArray(metadata.option_pricing) ? metadata.option_pricing.map((row: unknown) =>
    isObject(row) && typeof row.price_status === "string" ? row.price_status : "estimated") : options.map(() => "estimated")
  const overBudget = Array.isArray(metadata.option_pricing) ? metadata.option_pricing.map((row: unknown) =>
    isObject(row) && row.over_budget === true) : options.map(() => false)
  const estimates = metadata.estimated_routes ?? []
  if (!Array.isArray(estimates) || !estimates.every(isEstimatedRoute)) throw new Error("The search API returned invalid estimated routes.")
  const ranks = Array.isArray(metadata.option_pricing) ? metadata.option_pricing.map((row: unknown, index) =>
    isObject(row) && typeof row.rank === "number" ? row.rank : index + 1) : options.map((_, index) => index + 1)
  if (!signal?.aborted) onNotice?.(notices.join(" "), priceStatuses, overBudget, estimates, ranks)
  return options
}

function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
}

function isCity(value: unknown, id: unknown): boolean {
  return isObject(value) && value.id === id && typeof value.name === "string" &&
    typeof value.latitude === "number" && Number.isFinite(value.latitude) && Math.abs(value.latitude) <= 90 &&
    typeof value.longitude === "number" && Number.isFinite(value.longitude) && Math.abs(value.longitude) <= 180
}

function isRoundTripOption(value: unknown): value is RoundTripOption {
  if (!isObject(value) || !isObject(value.total_price) ||
      typeof value.total_price.amount !== "string" || !/^\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$/.test(value.total_price.amount) ||
      typeof value.total_price.currency !== "string" || !/^[A-Z]{3}$/.test(value.total_price.currency) ||
      !(value.stay_fit === null || typeof value.stay_fit === "number" && Number.isFinite(value.stay_fit) && value.stay_fit >= 0 && value.stay_fit <= 1) ||
      !Array.isArray(value.city_stays) || !value.city_stays.every((stay: unknown) =>
        isObject(stay) && typeof stay.city === "string" &&
        [stay.time_spent, stay.target_time, stay.attractiveness].every((n) => typeof n === "number" && Number.isFinite(n) && n >= 0)) ||
      !Array.isArray(value.path) || !value.path.length) return false
  return value.path.every((leg: unknown) => isObject(leg) &&
    typeof leg.from === "string" && typeof leg.to === "string" &&
    isCity(leg.from_city, leg.from) && isCity(leg.to_city, leg.to) &&
    typeof leg.departure_at === "string" && Number.isFinite(Date.parse(leg.departure_at)) &&
    typeof leg.arrival_at === "string" && Date.parse(leg.arrival_at) > Date.parse(leg.departure_at) &&
    typeof leg.time_in_travel === "number" && Number.isInteger(leg.time_in_travel) && leg.time_in_travel > 0 &&
    typeof leg.transport_type === "string" && ["PLANES", "TRAINS", "BUSSES", "FERRIES"].includes(leg.transport_type))
}

function isEstimatedRoute(value: unknown): value is EstimatedRoute {
  return isObject(value) && typeof value.rank === "number" && Number.isInteger(value.rank) && value.rank >= 1 && value.rank <= 10 &&
    Array.isArray(value.cities) && value.cities.length >= 4 && value.cities.every((city: unknown) => isObject(city) && typeof city.id === "string" && typeof city.name === "string") &&
    typeof value.departure_date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value.departure_date) && Number.isFinite(Date.parse(value.departure_date)) &&
    typeof value.return_date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value.return_date) && Number.isFinite(Date.parse(value.return_date)) &&
    isObject(value.total_price) && typeof value.total_price.amount === "string" && /^\d+(?:\.\d+)?$/.test(value.total_price.amount) &&
    value.total_price.currency === "EUR" && typeof value.schedule_source === "string"
}
