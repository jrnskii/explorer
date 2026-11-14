"use client"

import { Fragment } from "react"
import { ArrowRight, Bookmark, Bus, ChevronDown, Plane, Ship, TrainFront, type LucideIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Button } from "@/components/ui/button"

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { Skeleton } from "@/components/ui/skeleton"
import type {
  RoundTripOption,
  TransportType,
  TripLeg,
} from "@/generated/schema_v1"
import { tripId, useSavedTrips } from "@/lib/saved-trips"
import { cn } from "@/lib/utils"

const MODE: Record<TransportType, { label: string; Icon: LucideIcon }> = {
  TRAINS: { label: "Train", Icon: TrainFront },
  PLANES: { label: "Plane", Icon: Plane },
  BUSSES: { label: "Bus", Icon: Bus },
  FERRIES: { label: "Ferry", Icon: Ship },
}

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

// Manual UTC formatting: Intl output differs between Node and browsers
// (e.g. "4 Dec at 07:00" vs "4 Dec, 07:00"), which breaks hydration.
function formatClock(iso: string) {
  const d = new Date(iso)
  const hh = String(d.getUTCHours()).padStart(2, "0")
  const mm = String(d.getUTCMinutes()).padStart(2, "0")
  return `${hh}:${mm}`
}

function formatDay(iso: string) {
  const d = new Date(iso)
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`
}


function formatTime(iso: string) {
  return `${formatDay(iso)}, ${formatClock(iso)}`
}

function formatDuration(totalSeconds: number) {
  const minutes = Math.round(totalSeconds / 60)
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (h === 0) return `${m}m`
  return m === 0 ? `${h}h` : `${h}h ${m}m`
}

function formatPrice(amount: string, currency: string) {
  const n = Number(amount)
  try {
    return new Intl.NumberFormat("en-GB", {
      style: "currency",
      currency,
      minimumFractionDigits: Number.isInteger(n) ? 0 : 2,
    }).format(n)
  } catch {
    return `${amount} ${currency}`
  }
}


function layover(prev: TripLeg, next: TripLeg) {
  const seconds =
    (Date.parse(next.departure_at) - Date.parse(prev.arrival_at)) / 1000
  return seconds > 0 ? formatDuration(seconds) : null
}

function summarize(option: RoundTripOption) {
  const { path } = option
  const home = path[0].from
  const stops = [...new Set(path.map((l) => l.to))].filter((c) => c !== home)
  const travelSeconds = path.reduce((sum, l) => sum + l.time_in_travel, 0)
  const departAt = path[0].departure_at
  const returnAt = path[path.length - 1].arrival_at
  const totalSeconds = (Date.parse(returnAt) - Date.parse(departAt)) / 1000
  return { home, stops, travelSeconds, totalSeconds, departAt, returnAt }
}

// A plain vertical list: one full-width card per row, spaced with block margins.
const LIST = "w-full space-y-3"
const LIST_CARD = "w-full"

// Main section | divider | price + action, stacked on narrow screens.
const CARD_GRID = "grid sm:grid-cols-[1fr_13rem]"

function Endpoint({
  city,
  iso,
  align,
}: {
  city: string
  iso: string
  align: "start" | "end"
}) {
  return (
    <div
      className={cn(
        "min-w-0 shrink-0 max-w-[30%]",
        align === "end" && "text-right"
      )}
    >
      <div className="text-2xl font-medium tabular-nums leading-none sm:text-3xl">
        {formatClock(iso)}
      </div>
      <div className="mt-1 truncate text-sm text-muted-foreground">{city}</div>
      <div className="text-xs text-muted-foreground">{formatDay(iso)}</div>
    </div>
  )
}

export function TripOpportunity({
  option,
  rank,
  travelers = 1,
  priceScope = "adult",
  className,
}: {
  option: RoundTripOption
  rank?: number
  /** Prices are per adult; the total shown is multiplied by this. */
  travelers?: number
  priceScope?: "adult" | "party"
  className?: string
}) {
  const { home, travelSeconds, totalSeconds, departAt, returnAt } =
    summarize(option)
  const { trips, toggle } = useSavedTrips()
  const saved = trips.some((t) => t.id === tripId(option))

  return (
    <Card className={cn("gap-0 py-0", className)}>
      <Collapsible>
        <div className={CARD_GRID}>
          <div className="flex min-w-0 flex-col gap-4 p-4 sm:p-5">
            <div className="flex items-center gap-2">
              <div className="flex flex-1 flex-wrap items-center gap-1.5 text-sm">
                {rank === 1 && <Badge>Cheapest</Badge>}
                <span className="text-muted-foreground">
                  Round trip · {formatDuration(travelSeconds)} travelling
                </span>
              </div>
              <Button
                variant="ghost"
                size="icon"
                aria-pressed={saved}
                aria-label={saved ? "Remove from My trips" : "Save to My trips"}
                title={saved ? "Remove from My trips" : "Save to My trips"}
                onClick={() => toggle(option, travelers, priceScope)}
              >
                <Bookmark
                  aria-hidden
                  className={cn(saved && "fill-current")}
                />
              </Button>
            </div>

            <div className="flex items-start gap-3 sm:gap-4">
              <Endpoint city={home} iso={departAt} align="start" />

              <div className="min-w-0 flex-1 pt-0.5">
                <div className="text-center text-xs text-muted-foreground">
                  {formatDuration(totalSeconds)}
                </div>
                <ol
                  aria-label="Cities visited"
                  className="mt-6 flex items-start"
                >
                  {option.path.map((leg, i) => {
                    const { label, Icon } = MODE[leg.transport_type]
                    const isLast = i === option.path.length - 1
                    return (
                      <Fragment key={`${leg.from}-${leg.departure_at}`}>
                        <li
                          aria-hidden="true"
                          title={`${label}: ${leg.from} to ${leg.to}`}
                          className="relative h-2 min-w-6 flex-1"
                        >
                          <div className="absolute inset-x-0 top-1 h-px bg-border" />
                          <div className="absolute bottom-full left-1/2 mb-1 -translate-x-1/2 text-muted-foreground">
                            <Icon className="size-4" />
                          </div>
                        </li>
                        {!isLast && (
                          <li className="flex max-w-24 min-w-0 flex-col items-center gap-1">
                            <div className="size-2 shrink-0 rounded-full bg-primary" />
                            <div className="max-w-full text-center text-xs font-medium wrap-break-word">
                              {leg.to}
                            </div>
                          </li>
                        )}
                      </Fragment>
                    )
                  })}
                </ol>
              </div>

              <Endpoint city={home} iso={returnAt} align="end" />
            </div>
          </div>

          <div className="flex flex-col justify-between gap-3 border-t p-4 sm:border-t-0 sm:border-l sm:p-5">
            <div>
              <div className="text-xs text-muted-foreground">
                {priceScope === "party"
                  ? `estimated total for ${travelers} ${travelers === 1 ? "traveller" : "travellers"}`
                  : travelers === 1
                  ? "Price per adult"
                  : `Total for ${travelers} travellers`}
              </div>
              <div className="text-2xl font-semibold">
                {formatPrice(
                  priceScope === "party" ? option.total_price.amount : String(Number(option.total_price.amount) * travelers),
                  option.total_price.currency
                )}
              </div>
              {priceScope === "adult" && travelers > 1 && (
                <div className="text-xs text-muted-foreground">
                  {formatPrice(
                    option.total_price.amount,
                    option.total_price.currency
                  )}{" "}
                  each
                </div>
              )}
            </div>
            <div className="flex w-full">
              <Button size="lg" className="flex-1 rounded-r-none">
                Book
              </Button>
              <CollapsibleTrigger
                render={
                  <Button
                    size="icon-lg"
                    aria-label="Travel details"
                    title="Travel details"
                    className="group rounded-l-none border-l border-primary-foreground/30"
                  />
                }
              >
                <ChevronDown
                  aria-hidden
                  className="transition-transform group-aria-expanded:rotate-180 motion-reduce:transition-none"
                />
              </CollapsibleTrigger>
            </div>
          </div>
        </div>

        <CollapsibleContent>
          <ol className="flex flex-col border-t p-4 sm:px-5">
            {option.path.map((leg, i) => {
              const { label, Icon } = MODE[leg.transport_type]
              const wait = i > 0 ? layover(option.path[i - 1], leg) : null
              return (
                <li key={`${leg.from}-${leg.departure_at}`}>
                  {wait && (
                    <div className="py-1 pl-9 text-xs text-muted-foreground">
                      {wait} in {leg.from}
                    </div>
                  )}
                  <div className="flex items-center gap-3 rounded-lg px-1 py-2">
                    <span
                      className="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted"
                      title={label}
                    >
                      <Icon className="size-4" />
                      <span className="sr-only">{label}</span>
                    </span>
                    <div className="flex min-w-0 flex-1 items-center gap-2 text-sm font-medium">
                      <span className="truncate">{leg.from}</span>
                      <ArrowRight className="size-3.5 shrink-0 text-muted-foreground" />
                      <span className="truncate">{leg.to}</span>
                    </div>
                    <div className="shrink-0 text-right text-xs text-muted-foreground">
                      <div>
                        {formatTime(leg.departure_at)} →{" "}
                        {formatTime(leg.arrival_at)}
                      </div>
                      <div>{formatDuration(leg.time_in_travel)}</div>
                    </div>
                  </div>
                </li>
              )
            })}
          </ol>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  )
}

export function TripOpportunities({
  options,
  travelers = 1,
  priceScope = "adult",
  className,
}: {
  options: RoundTripOption[]
  travelers?: number
  priceScope?: "adult" | "party"
  className?: string
}) {
  return (
    <section
      aria-label="Travel opportunities"
      className={cn("flex flex-col gap-3", className)}
    >
      <h2 className="text-sm font-medium text-white">
        {options.length === 0
          ? "No travel opportunities match your search"
          : `${options.length} travel ${options.length === 1 ? "opportunity" : "opportunities"}`}
      </h2>
      <ul className={LIST}>
        {options.map((option, i) => (
          <li key={option.path.map((l) => l.departure_at).join("|")}>
            <TripOpportunity
              option={option}
              rank={i + 1}
              travelers={travelers}
            priceScope={priceScope}
              className={LIST_CARD}
            />
          </li>
        ))}
      </ul>
    </section>
  )
}

/** Skeleton cards shown before results exist (idle or loading). */
export function TripOpportunitiesPlaceholder({
  count = 3,
  className,
}: {
  count?: number
  className?: string
}) {
  return (
    <section
      aria-label="Travel opportunities"
      aria-busy="true"
      className={cn("flex flex-col gap-3", className)}
    >
      <h2 className="text-sm font-medium text-muted-foreground">
        Your travel opportunities will appear here
      </h2>
      <ul className={LIST}>
        {Array.from({ length: count }, (_, i) => (
          <li key={i}>
            <Card className={cn("gap-0 py-0", LIST_CARD)}>
              <div className={CARD_GRID}>
                <CardHeader className="gap-4 p-4 sm:p-5">
                  <Skeleton className="h-5 w-40" />
                  <div className="flex items-center gap-4">
                    <Skeleton className="h-10 w-16" />
                    <Skeleton className="h-4 flex-1" />
                    <Skeleton className="h-10 w-16" />
                  </div>
                </CardHeader>
                <CardContent className="flex flex-col gap-3 border-t p-4 sm:border-t-0 sm:border-l sm:p-5">
                  <Skeleton className="h-7 w-20" />
                  <Skeleton className="h-10 w-full" />
                </CardContent>
              </div>
            </Card>
          </li>
        ))}
      </ul>
    </section>
  )
}
