"use client";

import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import type { City } from "@/components/city-picker";
import { SiteHeader } from "@/components/site-header";
import {
  EMPTY_TRIP_INPUTS,
  TripInputs,
  type TripInputsValue,
} from "@/components/trip-inputs";
import { TripOpportunities } from "@/components/trip-opportunities";
import type { RoundTripOption } from "@/generated/schema_v1";
import { searchRoundTrips, type EstimatedRoute } from "@/lib/round-trip-search";
import { CloudOverlay } from "@/components/cloud-overlay";
import { EuropeLoader } from "@/components/europe-loader";
import { cn } from "@/lib/utils";

import { popularEuropeCities, searchEuropeCities } from "@/lib/europe-cities"
import { highlightTimeline } from "@/lib/europe-route-wave"
import { detectDepartureCity } from "@/lib/ip-origin"
import {
  cheapestOption,
  locateStops,
  stopNames,
  type LonLat,
} from "@/lib/trip-route"


// Stable reference: CityPicker re-runs its search effect when this changes.
const searchDeparture = (query: string) => searchEuropeCities(query);

// Transparent in the middle, fully opaque at the viewport borders: the blur fades in toward the edges.
const EDGE_MASK =
  "radial-gradient(ellipse at center, transparent 55%, black 100%)";

// Fades the page background colour in from the viewport borders (white in the light theme).
const VIGNETTE =
  "radial-gradient(ellipse at center, transparent 50%, color-mix(in srgb, var(--vignette) 85%, transparent) 100%)";

const DEFAULT_START_OFFSET_DAYS = 2;
const DEFAULT_DURATION = "3";

/** Local midnight, `days` days after today. */
function startDateFromToday(days: number, now = new Date()) {
  return new Date(now.getFullYear(), now.getMonth(), now.getDate() + days);
}

function subscribeToLocalDay(onChange: () => void) {
  window.addEventListener("focus", onChange);
  return () => window.removeEventListener("focus", onChange);
}

// Clouds thin to this share of their opacity while the map zooms.
const FLIGHT_CLOUD_DENSITY = 0.75


export default function Home() {
  const localDay = useSyncExternalStore(
    subscribeToLocalDay,
    () => new Date().toDateString(),
    () => "",
  );
  const [tripState, setTrip] = useState<
    Omit<TripInputsValue, "date"> & { date: Date | undefined | null }
  >({
    ...EMPTY_TRIP_INPUTS,
    date: null,
    duration: DEFAULT_DURATION,
  });
  const trip: TripInputsValue = {
    ...tripState,
    date:
      tripState.date === null
        ? localDay
          ? startDateFromToday(DEFAULT_START_OFFSET_DAYS, new Date(localDay))
          : undefined
        : tripState.date,
  };
  const [searchedTravelers, setSearchedTravelers] = useState(1);
  const [status, setStatus] = useState<"idle" | "loading" | "done" | "error">(
    "idle",
  );
  const [options, setOptions] = useState<RoundTripOption[]>([]);
  const [estimates, setEstimates] = useState<EstimatedRoute[]>([]);
  const [ranks, setRanks] = useState<number[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [priceStatuses, setPriceStatuses] = useState<string[]>([]);
  const [overBudgetOptions, setOverBudgetOptions] = useState<boolean[]>([]);
  const [flying, setFlying] = useState(false);
  const [searchNumber, setSearchNumber] = useState(0);
  const [revealedSearch, setRevealedSearch] = useState(0);
  const pending = useRef<AbortController | null>(null);

  useEffect(() => () => pending.current?.abort(), []);

  async function search(value: TripInputsValue) {
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setSearchedTravelers(value.travelers);
    setSearchNumber((number) => number + 1);
    setStatus("loading");
    setError("");
    setNotice("");
    setOptions([]);
    setEstimates([]);
    setRanks([]);
    try {
      const results = await searchRoundTrips(
        value,
        controller.signal,
        (message, statuses, overBudget, estimates = [], ranks = []) => {
          setEstimates(estimates);
          setRanks(ranks);
          setNotice(message);
          setPriceStatuses(statuses);
          setOverBudgetOptions(overBudget);
        },
      );
      if (controller.signal.aborted) return;
      setOptions(results);
      setStatus("done");
    } catch (failure) {
      if (controller.signal.aborted) return;
      setError(
        failure instanceof Error
          ? failure.message
          : "Trip search is unavailable.",
      );
      setStatus("error");
    }
  }
  // Departure auto-complete covers all European cities (lazy-loaded dataset).
  const [popular, setPopular] = useState<City[]>();
  useEffect(() => {
    let cancelled = false;
    popularEuropeCities().then((c) => !cancelled && setPopular(c));
    return () => {
      cancelled = true;
    };
  }, []);

  // Pre-fill the departure with the capital of the visitor's IP country,
  // unless the user picked a city before the lookup finished.
  useEffect(() => {
    const controller = new AbortController();
    detectDepartureCity(controller.signal).then((city) => {
      if (!city || controller.signal.aborted) return;
      setTrip((t) => (t.departure ? t : { ...t, departure: city }));
    });
    return () => controller.abort();
  }, []);

  // Glowing path of the cheapest option, once its stops are placed on the map.
  const cheapestStops = useMemo(() => {
    const estimate = estimates.find((route) => route.rank === 1)
    if (estimate) return estimate.cities.map((city) => city.name)
    const cheapest = cheapestOption(options)
    return cheapest ? stopNames(cheapest) : []
  }, [options, estimates])
  const departure = trip.departure
  const highlightKey = `${departure?.name ?? ""}|${cheapestStops.join(">")}`
  const [located, setLocated] = useState<{ key: string; points: LonLat[] } | null>(
    null
  )
  useEffect(() => {
    if (status !== "done" || cheapestStops.length === 0) return
    let cancelled = false
    locateStops(cheapestStops, departure, searchEuropeCities).then((points) => {
      if (!cancelled && points) setLocated({ key: highlightKey, points })
    }).catch(() => { /* An unavailable map lookup must not hide search results. */ })
    return () => {
      cancelled = true
    }
  }, [status, cheapestStops, departure, highlightKey])
  const highlight =
    status === "done" && located?.key === highlightKey ? located.points : undefined

  // The results wait while the white path is on screen on its own. Without a
  // path (stops not found) there is nothing to wait for.
  useEffect(() => {
    if (!highlight) return
    // The path zooms in, draws, then fades for 3 s; only then do the results show.
    const timer = setTimeout(
      () => setRevealedSearch(searchNumber),
      highlightTimeline(highlight).endMs
    )
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
        highlightLabels={highlight ? cheapestStops : undefined}
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
      {/* While searching only the map and its animation stay visible. The content
          stays mounted (form state is kept, layout does not shift) but is faded out
          and made inert so it cannot be focused or read by assistive technology. */}
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
            status !== "done" && "min-h-[70svh] justify-center",
          )}
        >
          <TripInputs
            value={trip}
            onChange={setTrip}
            cities={popular ?? []}
            onSearchDeparture={searchDeparture}
            departureSuggestions={popular}
            loading={status === "loading"}
            onSubmit={search}
          />
          {status === "error" && <p role="alert">{error}</p>}
          {status === "done" && !showcasing && (
            <>
              <TripOpportunities
                options={options}
                estimates={estimates}
                ranks={ranks}
                travelers={searchedTravelers}
                priceScope="adult"
                priceStatuses={priceStatuses}
                overBudgetOptions={overBudgetOptions}
              />
              <p role="status" className="text-sm text-muted-foreground">
                Up to 10 cheapest routes across departure dates ±1 day. The best
                estimate is checked with Scrappa/Omio, followed by the runner-up
                if verification fails. Other options remain estimates. Routes
                visit at least two destinations without repeating cities before
                returning home. Final fees require provider confirmation.
              </p>
              {notice && (
                <p role="status" className="text-sm text-muted-foreground">
                  {notice}
                </p>
              )}
            </>
          )}
        </main>
      </div>
    </>
  );
}
