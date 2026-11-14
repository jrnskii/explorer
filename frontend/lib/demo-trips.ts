/** Deterministic synthetic data used exclusively by the /demo route. */
import type { RoundTripOption } from "@/generated/schema_v1"
import type { LonLat } from "@/lib/trip-route"

export const DEMO_SHOWCASE_MS = 5000
export const DEMO_STOP_NAMES = ["Vilnius", "Warsaw", "Berlin", "Stockholm", "Riga", "Vilnius"]
export const DEMO_STOP_POINTS: LonLat[] = [
  [25.2797, 54.6872], [21.0122, 52.2297], [13.405, 52.52],
  [18.0686, 59.3293], [24.1052, 56.9496], [25.2797, 54.6872],
]

export const DEMO_OPTIONS: RoundTripOption[] = [{
  total_price: { amount: "149.00", currency: "EUR" },
  city_stays: [],
  stay_fit: null,
  path: DEMO_STOP_NAMES.slice(1).map((name, index) => {
    const from = DEMO_STOP_POINTS[index]
    const to = DEMO_STOP_POINTS[index + 1]
    const day = String(index + 1).padStart(2, "0")
    return {
      from: DEMO_STOP_NAMES[index], to: name,
      from_city: { id: DEMO_STOP_NAMES[index], name: DEMO_STOP_NAMES[index], longitude: from[0], latitude: from[1] },
      to_city: { id: name, name, longitude: to[0], latitude: to[1] },
      departure_at: `2030-06-${day}T08:00:00Z`,
      arrival_at: `2030-06-${day}T10:00:00Z`,
      time_in_travel: 7200,
      transport_type: "PLANES",
    }
  }),
}]
