"use client"

import { useEffect, useState } from "react"

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
  const [status, setStatus] = useState<"idle" | "loading" | "done">("idle")

  // Mock search: resolves with sample data after a short delay.
  useEffect(() => {
    if (status !== "loading") return
    const timer = setTimeout(() => setStatus("done"), 800)
    return () => clearTimeout(timer)
  }, [status])

  return (
    <div className="relative min-h-screen overflow-hidden">
      <div
        aria-hidden
        className="dots pointer-events-none absolute inset-x-0 top-0 h-[420px] opacity-60 [mask-image:linear-gradient(#000,transparent)]"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute top-52 -left-40 size-[380px] rounded-full bg-[#e4f4ee]"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -top-10 -right-48 size-[460px] rounded-full bg-[#dceef3]/70"
      />
      <div className="relative mx-auto w-full max-w-[1180px] px-4 sm:px-6">
        <SiteHeader />
        <main className="mt-4 flex flex-col gap-6 pb-16">
          <TripInputs
            value={trip}
            onChange={setTrip}
            cities={CITIES}
            loading={status === "loading"}
            onSubmit={() => setStatus("loading")}
          />
          {status === "loading" && <TripOpportunitiesPlaceholder />}
          {status === "done" && <TripOpportunities options={SAMPLE_OPTIONS} />}
        </main>
      </div>
    </div>
  )
}
