import type { City, RoundTripOption } from "@/generated/schema_v1"

import { TripOpportunities } from "./trip-opportunities"

// City-centre markers from the local Cities.csv snapshot (Work With Data, CC BY 4.0).
// These previews retain their existing city-name identifiers.
const CITIES = {
  Vilnius: { id: "Vilnius", name: "Vilnius", latitude: 54.6833333, longitude: 25.3166667 },
  Riga: { id: "Riga", name: "Riga", latitude: 56.95, longitude: 24.1 },
  Tallinn: { id: "Tallinn", name: "Tallinn", latitude: 59.4338889, longitude: 24.7280556 },
  Prague: { id: "Prague", name: "Prague", latitude: 50.083333, longitude: 14.466667 },
  Vienna: { id: "Vienna", name: "Vienna", latitude: 48.2, longitude: 16.366667 },
  Berlin: { id: "Berlin", name: "Berlin", latitude: 52.516667, longitude: 13.4 },
  Amsterdam: { id: "Amsterdam", name: "Amsterdam", latitude: 52.35, longitude: 4.916667 },
  Paris: { id: "Paris", name: "Paris", latitude: 48.866667, longitude: 2.333333 },
  Barcelona: { id: "Barcelona", name: "Barcelona", latitude: 41.398371, longitude: 2.1741 },
  Rome: { id: "Rome", name: "Rome", latitude: 41.9, longitude: 12.483333 },
} satisfies Record<string, City>

const SAMPLE_ROUTES: Omit<RoundTripOption, "city_stays">[] = [
  {
    total_price: { amount: "89.90", currency: "EUR" },
    path: [
      { from: "Vilnius", to: "Riga", from_city: CITIES.Vilnius, to_city: CITIES.Riga, departure_at: "2026-12-04T07:00:00Z", arrival_at: "2026-12-04T11:10:00Z", time_in_travel: 15000, transport_type: "BUSSES" },
      { from: "Riga", to: "Tallinn", from_city: CITIES.Riga, to_city: CITIES.Tallinn, departure_at: "2026-12-05T09:30:00Z", arrival_at: "2026-12-05T13:00:00Z", time_in_travel: 12600, transport_type: "BUSSES" },
      { from: "Tallinn", to: "Vilnius", from_city: CITIES.Tallinn, to_city: CITIES.Vilnius, departure_at: "2026-12-07T15:00:00Z", arrival_at: "2026-12-07T23:15:00Z", time_in_travel: 29700, transport_type: "BUSSES" },
    ],
  },
  {
    total_price: { amount: "148.90", currency: "EUR" },
    path: [
      { from: "Vilnius", to: "Prague", from_city: CITIES.Vilnius, to_city: CITIES.Prague, departure_at: "2026-12-04T06:10:00Z", arrival_at: "2026-12-04T07:55:00Z", time_in_travel: 6300, transport_type: "PLANES" },
      { from: "Prague", to: "Vienna", from_city: CITIES.Prague, to_city: CITIES.Vienna, departure_at: "2026-12-06T09:00:00Z", arrival_at: "2026-12-06T13:00:00Z", time_in_travel: 14400, transport_type: "TRAINS" },
      { from: "Vienna", to: "Vilnius", from_city: CITIES.Vienna, to_city: CITIES.Vilnius, departure_at: "2026-12-07T17:30:00Z", arrival_at: "2026-12-07T19:40:00Z", time_in_travel: 7800, transport_type: "PLANES" },
    ],
  },
  {
    total_price: { amount: "212", currency: "EUR" },
    path: [
      { from: "Vilnius", to: "Berlin", from_city: CITIES.Vilnius, to_city: CITIES.Berlin, departure_at: "2026-12-04T08:00:00Z", arrival_at: "2026-12-04T09:40:00Z", time_in_travel: 6000, transport_type: "PLANES" },
      { from: "Berlin", to: "Vilnius", from_city: CITIES.Berlin, to_city: CITIES.Vilnius, departure_at: "2026-12-07T18:00:00Z", arrival_at: "2026-12-07T21:30:00Z", time_in_travel: 12600, transport_type: "BUSSES" },
    ],
  },
  {
    total_price: { amount: "264.50", currency: "EUR" },
    path: [
      { from: "Vilnius", to: "Amsterdam", from_city: CITIES.Vilnius, to_city: CITIES.Amsterdam, departure_at: "2026-12-04T10:15:00Z", arrival_at: "2026-12-04T11:55:00Z", time_in_travel: 6000, transport_type: "PLANES" },
      { from: "Amsterdam", to: "Paris", from_city: CITIES.Amsterdam, to_city: CITIES.Paris, departure_at: "2026-12-05T08:20:00Z", arrival_at: "2026-12-05T11:40:00Z", time_in_travel: 12000, transport_type: "TRAINS" },
      { from: "Paris", to: "Barcelona", from_city: CITIES.Paris, to_city: CITIES.Barcelona, departure_at: "2026-12-06T14:00:00Z", arrival_at: "2026-12-06T16:05:00Z", time_in_travel: 7500, transport_type: "PLANES" },
      { from: "Barcelona", to: "Vilnius", from_city: CITIES.Barcelona, to_city: CITIES.Vilnius, departure_at: "2026-12-08T12:30:00Z", arrival_at: "2026-12-08T17:10:00Z", time_in_travel: 16800, transport_type: "PLANES" },
    ],
  },
  {
    total_price: { amount: "320", currency: "EUR" },
    path: [
      { from: "Vilnius", to: "Rome", from_city: CITIES.Vilnius, to_city: CITIES.Rome, departure_at: "2026-12-04T05:45:00Z", arrival_at: "2026-12-04T08:30:00Z", time_in_travel: 9900, transport_type: "PLANES" },
      { from: "Rome", to: "Vilnius", from_city: CITIES.Rome, to_city: CITIES.Vilnius, departure_at: "2026-12-08T19:00:00Z", arrival_at: "2026-12-08T21:50:00Z", time_in_travel: 10200, transport_type: "PLANES" },
    ],
  },
]

// Equal-weight stay targets for these synthetic preview routes.
export const SAMPLE_OPTIONS: RoundTripOption[] = SAMPLE_ROUTES.map((option) => {
  const home = option.path[0].from
  const spent = new Map<string, number>()
  option.path.forEach((leg, index) => {
    if (leg.to === home) return
    const next = option.path[index + 1]
    const seconds = next
      ? (Date.parse(next.departure_at) - Date.parse(leg.arrival_at)) / 1000
      : 0
    spent.set(leg.to, (spent.get(leg.to) ?? 0) + seconds)
  })
  const total = [...spent.values()].reduce((sum, seconds) => sum + seconds, 0)
  return {
    ...option,
    stay_fit: null,
    city_stays: [...spent].map(([city, time_spent]) => ({
      city, time_spent, target_time: total / spent.size, attractiveness: 1,
    })),
  }
})

export default function TripOpportunitiesPreview() {
  return <TripOpportunities options={SAMPLE_OPTIONS} estimatedRoutes={[{
    rank: 1, cities: ["Paris", "Berlin", "Rome", "Paris"].map(name => ({ id: name, name })),
    departure_date: "2030-01-01", return_date: "2030-01-04",
    total_price: { amount: "40.00", currency: "EUR" }, transport_types: ["TRAINS" as const, "TRAINS" as const, "TRAINS" as const], schedule_source: "reference",
  }]} />
}
