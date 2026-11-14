"use client"

import Link from "next/link"
import { Luggage } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { buttonVariants } from "@/components/ui/button"
import { useSavedTrips } from "@/lib/saved-trips"
import { cn } from "@/lib/utils"

export function MyTripsLink({
  current,
  className,
}: {
  current?: boolean
  className?: string
}) {
  const count = useSavedTrips().trips.length
  return (
    <Link
      href="/my-trips"
      aria-current={current ? "page" : undefined}
      className={cn(buttonVariants({ variant: "ghost" }), className)}
    >
      <Luggage aria-hidden strokeWidth={1.5} />
      My trips
      <Badge
        aria-label={`${count} saved ${count === 1 ? "trip" : "trips"}`}
        className="bg-badge text-forest"
      >
        {count}
      </Badge>
    </Link>
  )
}
