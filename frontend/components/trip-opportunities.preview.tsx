import type { RoundTripOption } from "@/generated/schema_v1"

import { TripOpportunities } from "./trip-opportunities"

export const SAMPLE_OPTIONS: RoundTripOption[] = [
  {
    total_price: { amount: "89.90", currency: "EUR" },
    path: [
      { from: "Vilnius", to: "Riga", departure_at: "2026-12-04T07:00:00Z", arrival_at: "2026-12-04T11:10:00Z", time_in_travel: 15000, transport_type: "BUSSES" },
      { from: "Riga", to: "Tallinn", departure_at: "2026-12-05T09:30:00Z", arrival_at: "2026-12-05T13:00:00Z", time_in_travel: 12600, transport_type: "BUSSES" },
      { from: "Tallinn", to: "Vilnius", departure_at: "2026-12-07T15:00:00Z", arrival_at: "2026-12-07T23:15:00Z", time_in_travel: 29700, transport_type: "BUSSES" },
    ],
  },
  {
    total_price: { amount: "148.90", currency: "EUR" },
    path: [
      { from: "Vilnius", to: "Prague", departure_at: "2026-12-04T06:10:00Z", arrival_at: "2026-12-04T07:55:00Z", time_in_travel: 6300, transport_type: "PLANES" },
      { from: "Prague", to: "Vienna", departure_at: "2026-12-06T09:00:00Z", arrival_at: "2026-12-06T13:00:00Z", time_in_travel: 14400, transport_type: "TRAINS" },
      { from: "Vienna", to: "Vilnius", departure_at: "2026-12-07T17:30:00Z", arrival_at: "2026-12-07T19:40:00Z", time_in_travel: 7800, transport_type: "PLANES" },
    ],
  },
  {
    total_price: { amount: "212", currency: "EUR" },
    path: [
      { from: "Vilnius", to: "Berlin", departure_at: "2026-12-04T08:00:00Z", arrival_at: "2026-12-04T09:40:00Z", time_in_travel: 6000, transport_type: "PLANES" },
      { from: "Berlin", to: "Vilnius", departure_at: "2026-12-07T18:00:00Z", arrival_at: "2026-12-07T21:30:00Z", time_in_travel: 12600, transport_type: "BUSSES" },
    ],
  },
  {
    total_price: { amount: "264.50", currency: "EUR" },
    path: [
      { from: "Vilnius", to: "Amsterdam", departure_at: "2026-12-04T10:15:00Z", arrival_at: "2026-12-04T11:55:00Z", time_in_travel: 6000, transport_type: "PLANES" },
      { from: "Amsterdam", to: "Paris", departure_at: "2026-12-05T08:20:00Z", arrival_at: "2026-12-05T11:40:00Z", time_in_travel: 12000, transport_type: "TRAINS" },
      { from: "Paris", to: "Barcelona", departure_at: "2026-12-06T14:00:00Z", arrival_at: "2026-12-06T16:05:00Z", time_in_travel: 7500, transport_type: "PLANES" },
      { from: "Barcelona", to: "Vilnius", departure_at: "2026-12-08T12:30:00Z", arrival_at: "2026-12-08T17:10:00Z", time_in_travel: 16800, transport_type: "PLANES" },
    ],
  },
  {
    total_price: { amount: "320", currency: "EUR" },
    path: [
      { from: "Vilnius", to: "Rome", departure_at: "2026-12-04T05:45:00Z", arrival_at: "2026-12-04T08:30:00Z", time_in_travel: 9900, transport_type: "PLANES" },
      { from: "Rome", to: "Vilnius", departure_at: "2026-12-08T19:00:00Z", arrival_at: "2026-12-08T21:50:00Z", time_in_travel: 10200, transport_type: "PLANES" },
    ],
  },
]

export default function TripOpportunitiesPreview() {
  return <TripOpportunities options={SAMPLE_OPTIONS} />
}
