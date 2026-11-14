"use client"

import { useEffect, useState } from "react"

import type { City } from "@/components/city-picker"
import { SiteHeader } from "@/components/site-header"
import {
  EMPTY_TRIP_INPUTS,
  TripInputs,
  type TripInputsValue,
} from "@/components/trip-inputs"
import { CloudOverlay } from "@/components/cloud-overlay"
import { EuropeLoader } from "@/components/europe-loader"
import { TripOpportunities } from "@/components/trip-opportunities"
import { SAMPLE_OPTIONS } from "@/components/trip-opportunities.preview"
import { cn } from "@/lib/utils"

import { popularEuropeCities, searchEuropeCities } from "@/lib/europe-cities"
import { detectDepartureCity } from "@/lib/ip-origin"

const CITIES: City[] = [
  { id: "lon", name: "London", country: "United Kingdom", code: "LON", lat: 51.5074, lon: -0.1278 },
  { id: "par", name: "Paris", country: "France", code: "PAR" },
  { id: "ber", name: "Berlin", country: "Germany", code: "BER" },
  { id: "rom", name: "Rome", country: "Italy", code: "ROM" },
  { id: "mad", name: "Madrid", country: "Spain", code: "MAD" },
  { id: "bcn", name: "Barcelona", country: "Spain", code: "BCN", lat: 41.3874, lon: 2.1686 },
  { id: "ams", name: "Amsterdam", country: "Netherlands", code: "AMS" },
  { id: "vno", name: "Vilnius", country: "Lithuania", code: "VNO" },
  { id: "prg", name: "Prague", country: "Czechia", code: "PRG" },
  { id: "nyc", name: "New York", country: "United States", code: "NYC", lat: 40.7128, lon: -74.006 },
  { id: "tyo", name: "Tokyo", country: "Japan", code: "TYO", lat: 35.6762, lon: 139.6503 },
]

// Stable reference: CityPicker re-runs its search effect when this changes.
const searchDeparture = (query: string) => searchEuropeCities(query)

// Transparent in the middle, fully opaque at the viewport borders: the blur fades in toward the edges.
const EDGE_MASK =
  "radial-gradient(ellipse at center, transparent 55%, black 100%)"

// Fades the page background colour in from the viewport borders (white in the light theme).
const VIGNETTE =
  "radial-gradient(ellipse at center, transparent 50%, color-mix(in srgb, var(--vignette) 85%, transparent) 100%)"

const MOCK_SEARCH_DELAY_MS = 10000

const DEFAULT_START_OFFSET_DAYS = 2
const DEFAULT_DURATION = "3"
const DEFAULT_BUDGET = "200"

/** Local midnight, `days` days after today. */
function startDateFromToday(days: number, now = new Date()) {
  return new Date(now.getFullYear(), now.getMonth(), now.getDate() + days)
}

export default function Home() {
  const [trip, setTrip] = useState<TripInputsValue>(EMPTY_TRIP_INPUTS)
  const [searchedTravelers, setSearchedTravelers] = useState(1)
  const [status, setStatus] = useState<"idle" | "loading" | "done">("idle")

  // Departure auto-complete covers all European cities (lazy-loaded dataset).
  const [popular, setPopular] = useState<City[]>()
  useEffect(() => {
    let cancelled = false
    popularEuropeCities().then((c) => !cancelled && setPopular(c))
    return () => {
      cancelled = true
    }
  }, [])

  // Default trip: leaves in 2 days, lasts 3 days, max 200 EUR. Set after mount
  // because "today" depends on the visitor's clock and must not differ from the
  // server-rendered HTML.
  useEffect(() => {
    setTrip((t) => ({
      ...t,
      date: t.date ?? startDateFromToday(DEFAULT_START_OFFSET_DAYS),
      duration: t.duration || DEFAULT_DURATION,
      budget: t.budget || DEFAULT_BUDGET,
    }))
  }, [])

  // Pre-fill the departure with the capital of the visitor's IP country,
  // unless the user picked a city before the lookup finished.
  useEffect(() => {
    const controller = new AbortController()
    detectDepartureCity(controller.signal).then((city) => {
      if (!city || controller.signal.aborted) return
      setTrip((t) => (t.departure ? t : { ...t, departure: city }))
    })
    return () => controller.abort()
  }, [])

  // Mock search: resolves with sample data after a fixed delay.
  useEffect(() => {
    if (status !== "loading") return
    const timer = setTimeout(() => setStatus("done"), MOCK_SEARCH_DELAY_MS)
    return () => clearTimeout(timer)
  }, [status])


  return (
    <>
      <EuropeLoader
        className="fixed inset-0 z-0 h-screen min-h-0"
        label="Finding your trip"
        departure={trip.departure}
        loading={status === "loading"}

        satellite
      />
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 z-[1] backdrop-blur-md"
        style={{ maskImage: EDGE_MASK, WebkitMaskImage: EDGE_MASK }}
      />
      <CloudOverlay
              className="fixed inset-0 z-[1] h-screen"
              denseTop={status !== "loading"}
            />
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 z-[1] [--vignette:white] dark:[--vignette:var(--background)]"
        style={{ background: VIGNETTE }}
      />
      {/* While searching only the map and its animation stay visible. The content
          stays mounted (form state is kept, layout does not shift) but is faded out
          and made inert so it cannot be focused or read by assistive technology. */}
      <div
        data-testid="page-content"
        inert={status === "loading"}
        className={cn(
          "relative z-10 mx-auto w-full max-w-5xl px-4 transition-opacity duration-500 motion-reduce:transition-none sm:px-6",
          status === "loading" && "pointer-events-none opacity-0"
        )}
      >
        <SiteHeader />
        <main
                  className={cn(
                    "flex flex-col gap-6 py-6",
                    status !== "done" && "min-h-[70svh] justify-center"
                  )}
                >
        <TripInputs
          value={trip}
          onChange={setTrip}
          cities={CITIES}
          onSearchDeparture={searchDeparture}
          departureSuggestions={popular}
          loading={status === "loading"}
          onSubmit={(v) => {
            setSearchedTravelers(v.travelers)
            setStatus("loading")
          }}
        />

        {status === "done" && (
          <TripOpportunities
            options={SAMPLE_OPTIONS}
            travelers={searchedTravelers}
          />
        )}
        </main>
      </div>
    </>
  )
}
