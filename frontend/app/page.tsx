"use client"

import { useEffect, useRef, useState } from "react"

import type { City } from "@/components/city-picker"
import { SiteHeader } from "@/components/site-header"
import {
  EMPTY_TRIP_INPUTS,
  TripInputs,
  type TripInputsValue,
} from "@/components/trip-inputs"
import {
  TripOpportunities,
  TripOpportunitiesPlaceholder,
} from "@/components/trip-opportunities"
import type { RoundTripOption } from "@/generated/schema_v1"
import { priceSamples } from "@/lib/sample-forecast"
import { SAMPLE_OPTIONS } from "@/components/trip-opportunities.preview"

const CITIES: City[] = [
  { id: "lon", name: "London", country: "United Kingdom", code: "LON" },
  { id: "par", name: "Paris", country: "France", code: "PAR" },
  { id: "ber", name: "Berlin", country: "Germany", code: "BER" },
  { id: "rom", name: "Rome", country: "Italy", code: "ROM" },
  { id: "mad", name: "Madrid", country: "Spain", code: "MAD" },
  { id: "bcn", name: "Barcelona", country: "Spain", code: "BCN" },
  { id: "ams", name: "Amsterdam", country: "Netherlands", code: "AMS" },
  { id: "vno", name: "Vilnius", country: "Lithuania", code: "VNO" },
  { id: "prg", name: "Prague", country: "Czechia", code: "PRG" },
  { id: "nyc", name: "New York", country: "United States", code: "NYC" },
  { id: "tyo", name: "Tokyo", country: "Japan", code: "TYO" },
]

export default function Home() {
  const [trip, setTrip] = useState<TripInputsValue>(EMPTY_TRIP_INPUTS)
  const [searchedTravelers, setSearchedTravelers] = useState(1)
  const [status, setStatus] = useState<"idle" | "loading" | "done" | "error">("idle")
  const [options, setOptions] = useState<RoundTripOption[]>([])
  const [error, setError] = useState("")
  const pending = useRef<AbortController | null>(null)

  useEffect(() => () => pending.current?.abort(), [])

  async function search(value: TripInputsValue) {
    pending.current?.abort()
    const controller = new AbortController()
    pending.current = controller
    setSearchedTravelers(value.travelers)
    setStatus("loading")
    setError("")
    setOptions([])
    try {
      const estimates = await priceSamples(SAMPLE_OPTIONS, value, controller.signal)
      if (controller.signal.aborted) return
      setOptions(estimates)
      setStatus("done")
    } catch (failure) {
      if (controller.signal.aborted) return
      setError(failure instanceof Error ? failure.message : "Price estimates are unavailable.")
      setStatus("error")
    }
  }

  return (
    <div className="mx-auto w-full max-w-5xl px-4 sm:px-6">
      <SiteHeader />
      <main className="flex flex-col gap-6 py-6">
        <TripInputs
          value={trip}
          onChange={setTrip}
          cities={CITIES}
          loading={status === "loading"}
          onSubmit={search}
        />
        <p className="text-sm text-muted-foreground">
          Sample itineraries with estimated fares. Schedules are illustrative, not bookable.
          Routes without supported pricing are omitted.
        </p>
        {status === "error" && <p role="alert">{error}</p>}
        {status === "loading" && <TripOpportunitiesPlaceholder />}
        {status === "done" && (
          <TripOpportunities
            options={options}
            travelers={searchedTravelers}
            priceScope="party"
          />
        )}
      </main>
    </div>
  )
}
