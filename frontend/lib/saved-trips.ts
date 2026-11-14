"use client"

import { useCallback, useSyncExternalStore } from "react"

import type { RoundTripOption } from "@/generated/schema_v1"

export const SAVED_TRIPS_KEY = "explorer:saved-trips"

export type SavedTrip = {
  id: string
  option: RoundTripOption
  /** Traveller count of the search the trip was saved from. */
  travelers: number
  /** ISO timestamp of when the trip was saved. */
  savedAt: string
}

const EMPTY: SavedTrip[] = []
const listeners = new Set<() => void>()

let cachedRaw: string | null = null
let cachedTrips: SavedTrip[] = EMPTY

/** Stable identity of an itinerary: its legs' endpoints and departure times. */
export function tripId(option: RoundTripOption): string {
  return option.path
    .map((l) => `${l.from}>${l.to}@${l.departure_at}`)
    .join("|")
}

function isSavedTrip(value: unknown): value is SavedTrip {
  if (typeof value !== "object" || value === null) return false
  const v = value as Partial<SavedTrip>
  const option = v.option as Partial<RoundTripOption> | undefined
  return (
    typeof v.id === "string" &&
    typeof v.savedAt === "string" &&
    typeof v.travelers === "number" &&
    Array.isArray(option?.path) &&
    option.path.length > 0 &&
    typeof option.total_price?.amount === "string" &&
    typeof option.total_price?.currency === "string"
  )
}

function parse(raw: string | null): SavedTrip[] {
  if (!raw) return EMPTY
  try {
    const data: unknown = JSON.parse(raw)
    if (!Array.isArray(data)) return EMPTY
    const trips = data.filter(isSavedTrip)
    return trips.length ? trips : EMPTY
  } catch {
    return EMPTY
  }
}

function readRaw(): string | null {
  try {
    return window.localStorage.getItem(SAVED_TRIPS_KEY)
  } catch {
    return null
  }
}

export function getSavedTrips(): SavedTrip[] {
  const raw = readRaw()
  if (raw !== cachedRaw) {
    cachedRaw = raw
    cachedTrips = parse(raw)
  }
  return cachedTrips
}

function write(trips: SavedTrip[]) {
  try {
    window.localStorage.setItem(SAVED_TRIPS_KEY, JSON.stringify(trips))
  } catch {
    // Storage unavailable or full: keep in-memory state consistent only.
    cachedRaw = null
    cachedTrips = trips
  }
  listeners.forEach((l) => l())
}

export function saveTrip(option: RoundTripOption, travelers = 1) {
  const id = tripId(option)
  const current = getSavedTrips()
  if (current.some((t) => t.id === id)) return
  write([
    { id, option, travelers, savedAt: new Date().toISOString() },
    ...current,
  ])
}

export function removeTrip(id: string) {
  const current = getSavedTrips()
  if (!current.some((t) => t.id === id)) return
  write(current.filter((t) => t.id !== id))
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  const onStorage = (e: StorageEvent) => {
    if (e.key === null || e.key === SAVED_TRIPS_KEY) listener()
  }
  window.addEventListener("storage", onStorage)
  return () => {
    listeners.delete(listener)
    window.removeEventListener("storage", onStorage)
  }
}

export function useSavedTrips() {
  const trips = useSyncExternalStore(subscribe, getSavedTrips, () => EMPTY)
  const toggle = useCallback((option: RoundTripOption, travelers = 1) => {
    const id = tripId(option)
    if (getSavedTrips().some((t) => t.id === id)) removeTrip(id)
    else saveTrip(option, travelers)
  }, [])
  return { trips, toggle, remove: removeTrip }
}
