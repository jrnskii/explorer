import { ArrowRight, Bus, Plane, Ship, TrainFront, type LucideIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import type {
  RoundTripOption,
  TransportType,
  TripLeg,
} from "@/generated/schema_v1"
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
function formatTime(iso: string) {
  const d = new Date(iso)
  const hh = String(d.getUTCHours()).padStart(2, "0")
  const mm = String(d.getUTCMinutes()).padStart(2, "0")
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}, ${hh}:${mm}`
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
  const totalSeconds =
    (Date.parse(path[path.length - 1].arrival_at) -
      Date.parse(path[0].departure_at)) /
    1000
  const modes = [...new Set(path.map((l) => l.transport_type))]
  return { home, stops, travelSeconds, totalSeconds, modes }
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
  const { home, stops, travelSeconds, totalSeconds, modes } = summarize(option)

  return (
    <Card className={className}>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <CardTitle className="flex flex-wrap items-center gap-x-2 text-base">
              {rank === 1 && <Badge>Cheapest</Badge>}
              <span className="truncate">
                {stops.length ? stops.join(" · ") : home}
              </span>
            </CardTitle>
            <CardDescription>
              Round trip from {home} · {formatDuration(totalSeconds)} total ·{" "}
              {formatDuration(travelSeconds)} travelling
            </CardDescription>
          </div>
          <div className="shrink-0 text-right">
            <div className="text-xl font-semibold">
              {formatPrice(
                priceScope === "party" ? option.total_price.amount : String(Number(option.total_price.amount) * travelers),
                option.total_price.currency
              )}
            </div>
            <div className="text-xs text-muted-foreground">
              {priceScope === "party"
                ? `estimated total for ${travelers} ${travelers === 1 ? "traveller" : "travellers"}`
                : travelers === 1
                ? "per adult"
                : `for ${travelers} travellers · ${formatPrice(
                    option.total_price.amount,
                    option.total_price.currency
                  )} each`}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5 pt-1">
          {modes.map((m) => {
            const { label, Icon } = MODE[m]
            return (
              <Badge key={m} variant="secondary">
                <Icon className="size-3" />
                {label}
              </Badge>
            )
          })}
        </div>
      </CardHeader>

      <CardContent>
        <ol className="flex flex-col">
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
                    className={cn(
                      "flex size-7 shrink-0 items-center justify-center rounded-full bg-muted"
                    )}
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
      </CardContent>
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
      <h2 className="text-sm font-medium text-muted-foreground">
        {options.length === 0
          ? "No travel opportunities match your search"
          : `${options.length} travel ${options.length === 1 ? "opportunity" : "opportunities"}`}
      </h2>
      {options.map((option, i) => (
        <TripOpportunity
          key={option.path.map((l) => l.departure_at).join("|")}
          option={option}
          rank={i + 1}
          travelers={travelers}
          priceScope={priceScope}
        />
      ))}
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
      {Array.from({ length: count }, (_, i) => (
        <Card key={i}>
          <CardHeader>
            <div className="flex items-start justify-between gap-4">
              <div className="flex flex-1 flex-col gap-2">
                <Skeleton className="h-5 w-40" />
                <Skeleton className="h-4 w-64 max-w-full" />
              </div>
              <Skeleton className="h-7 w-16" />
            </div>
            <div className="flex gap-1.5 pt-1">
              <Skeleton className="h-5 w-16 rounded-full" />
              <Skeleton className="h-5 w-16 rounded-full" />
            </div>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {[0, 1].map((j) => (
              <div key={j} className="flex items-center gap-3">
                <Skeleton className="size-7 rounded-full" />
                <Skeleton className="h-4 flex-1" />
                <Skeleton className="h-8 w-28" />
              </div>
            ))}
          </CardContent>
        </Card>
      ))}
    </section>
  )
}
