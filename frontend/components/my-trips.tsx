"use client"

import Link from "next/link"
import { Luggage, Search } from "lucide-react"

import { TripOpportunity } from "@/components/trip-opportunities"
import { buttonVariants } from "@/components/ui/button"
import { useSavedTrips } from "@/lib/saved-trips"
import { cn } from "@/lib/utils"

export function MyTrips({ className }: { className?: string }) {
  const { trips } = useSavedTrips()

  return (
    <section
      aria-label="Saved trips"
      className={cn("flex flex-col gap-4", className)}
    >
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">My trips</h1>
        <p className="text-sm text-muted-foreground" aria-live="polite">
          {trips.length === 0
            ? "You have no saved trips yet."
            : `${trips.length} saved ${trips.length === 1 ? "trip" : "trips"}, stored in this browser.`}
        </p>
      </div>

      {trips.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed bg-card/80 px-4 py-12 text-center">
          <Luggage
            aria-hidden
            strokeWidth={1.5}
            className="size-10 text-muted-foreground"
          />
          <p className="max-w-sm text-sm text-muted-foreground">
            Save a trip with the bookmark button on any search result and it
            will appear here.
          </p>
          <Link href="/" className={buttonVariants()}>
            <Search aria-hidden />
            Search trips
          </Link>
        </div>
      ) : (
        <ul className="w-full space-y-3">
          {trips.map((trip) => (
            <li key={trip.id}>
              <TripOpportunity
                option={trip.option}
                travelers={trip.travelers}
                priceScope={trip.priceScope}
                className="w-full"
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
