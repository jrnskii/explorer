"use client"

import { useEffect, useRef, useState, useSyncExternalStore } from "react"

import type { City } from "@/components/city-picker"
import { CloudOverlay } from "@/components/cloud-overlay"
import { EuropeLoader } from "@/components/europe-loader"
import { SiteHeader } from "@/components/site-header"
import {
  EMPTY_TRIP_INPUTS,
  TripInputs,
  type TripInputsValue,
} from "@/components/trip-inputs"
import { TripOpportunities } from "@/components/trip-opportunities"
import {
  DEMO_OPTIONS,
  DEMO_SHOWCASE_MS,
  DEMO_STOP_NAMES,
  DEMO_STOP_POINTS,
} from "@/lib/demo-trips"
import { popularEuropeCities, searchEuropeCities } from "@/lib/europe-cities"
import { cn } from "@/lib/utils"

const VILNIUS: City = {
  id: "vno",
  name: "Vilnius",
  country: "Lithuania",
  code: "VNO",
  lat: 54.6872,
  lon: 25.2797,
}

const CITIES: City[] = [VILNIUS]

const searchDeparture = (query: string) => searchEuropeCities(query)

const EDGE_MASK = "radial-gradient(ellipse at center, transparent 55%, black 100%)"
const VIGNETTE =
  "radial-gradient(ellipse at center, transparent 50%, color-mix(in srgb, var(--vignette) 85%, transparent) 100%)"
const FLIGHT_CLOUD_DENSITY = 0.75

const DEFAULT_START_OFFSET_DAYS = 2
const DEFAULT_DURATION = "3"

/** Local midnight, `days` days after today. */
function startDateFromToday(days: number, now = new Date()) {
  return new Date(now.getFullYear(), now.getMonth(), now.getDate() + days)
}

/**
 * The homepage with a scripted outcome for demonstrations: whatever is searched,
 * the same synthetic Vilnius > Warsaw > Berlin > Stockholm > Riga > Vilnius trip
 * is showcased for exactly `DEMO_SHOWCASE_MS` and listed as the best match.
 */
function subscribeToLocalDay(onChange: () => void) {
  window.addEventListener("focus", onChange)
  return () => window.removeEventListener("focus", onChange)
}

export function DemoHome() {
  const localDay = useSyncExternalStore(subscribeToLocalDay, () => new Date().toDateString(), () => "")
  const [tripState, setTrip] = useState<TripInputsValue>({
    ...EMPTY_TRIP_INPUTS,
    departure: VILNIUS,
    duration: DEFAULT_DURATION,
  })
  const trip = {
    ...tripState,
    date: tripState.date ?? (localDay ? startDateFromToday(DEFAULT_START_OFFSET_DAYS, new Date(localDay)) : undefined),
  }
  const [searchedTravelers, setSearchedTravelers] = useState(1)
  const [status, setStatus] = useState<"idle" | "loading" | "done">("idle")
  const [flying, setFlying] = useState(false)
  const [searchNumber, setSearchNumber] = useState(0)
  const [revealedSearch, setRevealedSearch] = useState(0)
  const [popular, setPopular] = useState<City[]>()
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => () => void (pending.current && clearTimeout(pending.current)), [])

  useEffect(() => {
    let cancelled = false
    popularEuropeCities().then((c) => !cancelled && setPopular(c))
    return () => {
      cancelled = true
    }
  }, [])

  function search(value: TripInputsValue) {
    if (pending.current) clearTimeout(pending.current)
    setSearchedTravelers(value.travelers)
    setSearchNumber((n) => n + 1)
    setStatus("loading")
    // A brief "searching" beat, then the scripted result.
    pending.current = setTimeout(() => setStatus("done"), 600)
  }

  const highlight = status === "done" ? DEMO_STOP_POINTS : undefined

  useEffect(() => {
    if (!highlight) return
    const timer = setTimeout(() => setRevealedSearch(searchNumber), DEMO_SHOWCASE_MS)
    return () => clearTimeout(timer)
  }, [highlight, searchNumber])

  const showcasing = highlight !== undefined && revealedSearch !== searchNumber
  const hidden = status === "loading" || showcasing

  return (
    <>
      <EuropeLoader
        className="fixed inset-0 z-0 h-screen min-h-0"
        label="Finding your trip"
        departure={trip.departure}
        loading={status === "loading"}
        highlight={highlight}
        highlightLabels={highlight ? DEMO_STOP_NAMES : undefined}
        highlightDurationMs={DEMO_SHOWCASE_MS}
        onFlight={setFlying}
        satellite
      />
      <div
        aria-hidden
        data-flying={flying}
        className={cn(
          "pointer-events-none fixed inset-0 z-[1] backdrop-blur-md transition-opacity duration-300 motion-reduce:transition-none",
          flying && "opacity-0"
        )}
        style={{ maskImage: EDGE_MASK, WebkitMaskImage: EDGE_MASK }}
      />
      <CloudOverlay
        className="fixed inset-0 z-[1] h-screen"
        denseTop={!hidden}
        density={flying ? FLIGHT_CLOUD_DENSITY : 1}
      />
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 z-[1] [--vignette:white] dark:[--vignette:var(--background)]"
        style={{ background: VIGNETTE }}
      />
      <div
        data-testid="page-content"
        inert={hidden}
        className={cn(
          "relative z-10 mx-auto w-full max-w-5xl px-4 transition-opacity duration-500 motion-reduce:transition-none sm:px-6",
          hidden && "pointer-events-none opacity-0"
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
            onSubmit={search}
          />
          {status === "done" && (
            <>
              <TripOpportunities
                options={DEMO_OPTIONS}
                travelers={searchedTravelers}
                priceScope="adult"
                featuredIndex={0}
                featuredLabel="Best match"
              />
              <p className="text-xs text-muted-foreground">
                Demo data: schedules and fares are illustrative, not real availability.
              </p>
            </>
          )}
        </main>
      </div>
    </>
  )
}
