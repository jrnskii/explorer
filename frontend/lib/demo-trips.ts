/** Deterministic synthetic data used exclusively by the /demo route. Not real schedules or prices. */
import type { RoundTripOption, TransportType } from "@/generated/schema_v1"
import type { LonLat } from "@/lib/trip-route"

/** Simulated search latency before the route showcase starts. */
export const DEMO_SEARCH_MS = 1500
export const DEMO_SHOWCASE_MS = 5000
export const DEMO_STOP_NAMES = ["Vilnius", "Warsaw", "Berlin", "Stockholm", "Riga", "Vilnius"]
export const DEMO_STOP_POINTS: LonLat[] = [
  [25.2797, 54.6872], [21.0122, 52.2297], [13.405, 52.52],
  [18.0686, 59.3293], [24.1052, 56.9496], [25.2797, 54.6872],
]

interface DemoLeg {
  transport: TransportType
  /** Departure hour (UTC) on the leg's day. */
  hour: number
  hours: number
}

function demoOption(price: string, legs: DemoLeg[]): RoundTripOption {
  return {
    total_price: { amount: price, currency: "EUR" },
    city_stays: [],
    stay_fit: null,
    path: legs.map((leg, index) => {
      const from = DEMO_STOP_NAMES[index]
      const to = DEMO_STOP_NAMES[index + 1]
      const departure = Date.UTC(2030, 5, index + 1, leg.hour)
      return {
        from,
        to,
        from_city: { id: from, name: from, longitude: DEMO_STOP_POINTS[index][0], latitude: DEMO_STOP_POINTS[index][1] },
        to_city: { id: to, name: to, longitude: DEMO_STOP_POINTS[index + 1][0], latitude: DEMO_STOP_POINTS[index + 1][1] },
        departure_at: new Date(departure).toISOString(),
        arrival_at: new Date(departure + leg.hours * 3_600_000).toISOString(),
        time_in_travel: leg.hours * 3600,
        transport_type: leg.transport,
      }
    }),
  }
}

export const DEMO_BEST_OPTION = demoOption("149.00", [
  { transport: "TRAINS", hour: 6, hours: 8 },
  { transport: "PLANES", hour: 8, hours: 2 },
  { transport: "PLANES", hour: 8, hours: 2 },
  { transport: "PLANES", hour: 8, hours: 2 },
  { transport: "BUSSES", hour: 8, hours: 4 },
])

export const DEMO_OPTIONS: RoundTripOption[] = [
  DEMO_BEST_OPTION,
  demoOption("187.00", [
    { transport: "BUSSES", hour: 6, hours: 9 },
    { transport: "PLANES", hour: 9, hours: 2 },
    { transport: "FERRIES", hour: 9, hours: 12 },
    { transport: "PLANES", hour: 8, hours: 2 },
    { transport: "BUSSES", hour: 9, hours: 4 },
  ]),
  demoOption("214.00", [
    { transport: "PLANES", hour: 7, hours: 2 },
    { transport: "TRAINS", hour: 7, hours: 6 },
    { transport: "PLANES", hour: 10, hours: 2 },
    { transport: "PLANES", hour: 10, hours: 2 },
    { transport: "TRAINS", hour: 8, hours: 5 },
  ]),
]
