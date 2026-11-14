"use client"

import * as React from "react"
import {
  ArrowLeftRight,
  ArrowRight,
  ChevronDown,
  Minus,
  Plus,
  Armchair,
  Search,
  User,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Calendar } from "@/components/ui/calendar"
import { Input } from "@/components/ui/input"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { cn } from "@/lib/utils"

export type TripType = "round-trip" | "one-way"
export type Cabin = "economy" | "premium-economy" | "business" | "first"

export type FlightSearchValue = {
  from: string
  to: string
  departDate: Date | undefined
  /** Only meaningful for round trips. */
  returnDate: Date | undefined
  tripType: TripType
  passengers: number
  cabin: Cabin
}

export const EMPTY_FLIGHT_SEARCH: FlightSearchValue = {
  from: "",
  to: "",
  departDate: undefined,
  returnDate: undefined,
  tripType: "round-trip",
  passengers: 1,
  cabin: "economy",
}

const TRIP_TYPES: { value: TripType; label: string }[] = [
  { value: "round-trip", label: "Round trip" },
  { value: "one-way", label: "One way" },
]

const CABINS: { value: Cabin; label: string }[] = [
  { value: "economy", label: "Economy" },
  { value: "premium-economy", label: "Premium economy" },
  { value: "business", label: "Business" },
  { value: "first", label: "First" },
]

const MIN_PASSENGERS = 1
const MAX_PASSENGERS = 9

const dateFormat = new Intl.DateTimeFormat("en-GB", {
  weekday: "short",
  month: "short",
  day: "numeric",
})

/** A search can run once both places differ and a departure date is chosen. */
export function isFlightSearchComplete(v: FlightSearchValue) {
  const from = v.from.trim().toLowerCase()
  const to = v.to.trim().toLowerCase()
  if (!from || !to || from === to || !v.departDate) return false
  return v.tripType === "one-way" || v.returnDate !== undefined
}

const segmentLabel = "text-xs font-medium text-muted-foreground"
const segmentInput =
  "h-auto! border-0! bg-transparent! p-0! text-base! font-medium shadow-none! ring-0! focus-visible:ring-0! dark:bg-transparent!"
const pillTrigger =
  "h-9! w-auto! gap-2 rounded-full! border-0! bg-transparent! px-3! text-sm! font-medium hover:bg-muted! dark:bg-transparent!"

function Passengers({
  value,
  onChange,
}: {
  value: number
  onChange: (n: number) => void
}) {
  const labelId = React.useId()
  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button
            type="button"
            variant="ghost"
            className="h-9 rounded-full px-3 text-sm font-medium"
          />
        }
      >
        <User aria-hidden />
        {value === 1 ? "1 passenger" : `${value} passengers`}
        <ChevronDown aria-hidden className="text-muted-foreground" />
      </PopoverTrigger>
      <PopoverContent align="center" className="w-64">
        <div className="flex items-center justify-between gap-4">
          <span id={labelId} className="text-sm font-medium">
            Passengers
          </span>
          <div
            role="group"
            aria-labelledby={labelId}
            className="flex items-center gap-3"
          >
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label="Remove a passenger"
              disabled={value <= MIN_PASSENGERS}
              onClick={() => onChange(Math.max(MIN_PASSENGERS, value - 1))}
            >
              <Minus />
            </Button>
            <output
              aria-live="polite"
              className="w-4 text-center font-semibold tabular-nums"
            >
              {value}
            </output>
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label="Add a passenger"
              disabled={value >= MAX_PASSENGERS}
              onClick={() => onChange(Math.min(MAX_PASSENGERS, value + 1))}
            >
              <Plus />
            </Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  )
}

function DatesSegment({
  value,
  onChange,
  idPrefix,
}: {
  value: FlightSearchValue
  onChange: (patch: Partial<FlightSearchValue>) => void
  idPrefix: string
}) {
  const [open, setOpen] = React.useState(false)
  const [today, setToday] = React.useState<Date>()
  const oneWay = value.tripType === "one-way"

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        if (next) setToday(new Date())
        setOpen(next)
      }}
    >
      <PopoverTrigger
        render={
          <button
            id={`${idPrefix}-dates`}
            type="button"
            className="flex min-w-0 flex-1 flex-col items-start gap-0.5 rounded-2xl px-5 py-3 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50 lg:rounded-none"
          />
        }
      >
        <span className={segmentLabel}>Dates</span>
        <span className="flex items-center gap-2 text-base font-medium">
          <span className={cn(!value.departDate && "text-muted-foreground")}>
            {value.departDate ? dateFormat.format(value.departDate) : "Add date"}
          </span>
          {!oneWay && (
            <>
              <ArrowRight
                aria-hidden
                className="size-4 text-muted-foreground"
              />
              <span
                className={cn(!value.returnDate && "text-muted-foreground")}
              >
                {value.returnDate
                  ? dateFormat.format(value.returnDate)
                  : "Add return"}
              </span>
            </>
          )}
        </span>
      </PopoverTrigger>
      <PopoverContent align="center" className="w-auto p-0">
        {oneWay ? (
          <Calendar
            mode="single"
            selected={value.departDate}
            defaultMonth={value.departDate}
            onSelect={(d) => {
              onChange({ departDate: d, returnDate: undefined })
              if (d) setOpen(false)
            }}
            disabled={today ? { before: today } : undefined}
            autoFocus
          />
        ) : (
          <Calendar
            mode="range"
            numberOfMonths={2}
            selected={{ from: value.departDate, to: value.returnDate }}
            defaultMonth={value.departDate}
            onSelect={(range) => {
              onChange({ departDate: range?.from, returnDate: range?.to })
              if (range?.from && range.to) setOpen(false)
            }}
            disabled={today ? { before: today } : undefined}
            autoFocus
          />
        )}
      </PopoverContent>
    </Popover>
  )
}

type FlightSearchFormProps = {
  value: FlightSearchValue
  onChange: (value: FlightSearchValue) => void
  /** Called when the user submits a complete search. */
  onSubmit?: (value: FlightSearchValue) => void
  className?: string
}

/** Pill-shaped flight search: places and dates in one bar, trip options below. */
export function FlightSearchForm({
  value,
  onChange,
  onSubmit,
  className,
}: FlightSearchFormProps) {
  const id = React.useId()
  const patch = (p: Partial<FlightSearchValue>) => onChange({ ...value, ...p })
  const complete = isFlightSearchComplete(value)

  return (
    <form
      aria-label="Flight search"
      noValidate
      onSubmit={(e) => {
        e.preventDefault()
        if (complete) onSubmit?.(value)
      }}
      className={cn("flex flex-col items-center gap-4", className)}
    >
      <div className="flex w-full flex-col gap-2 rounded-3xl bg-background/60 p-2 shadow-lg ring-1 ring-foreground/5 backdrop-blur-md lg:flex-row lg:items-center lg:rounded-full">
        <div className="flex flex-1 flex-col divide-y rounded-2xl bg-background lg:flex-row lg:items-center lg:divide-x lg:divide-y-0 lg:rounded-full">
          <div className="relative flex min-w-0 flex-1 items-center">
            <label
              htmlFor={`${id}-from`}
              className="flex min-w-0 flex-1 flex-col gap-0.5 rounded-2xl px-5 py-3 focus-within:bg-muted/50 lg:rounded-none lg:rounded-l-full"
            >
              <span className={segmentLabel}>From</span>
              <Input
                id={`${id}-from`}
                autoComplete="off"
                placeholder="City or airport"
                value={value.from}
                onChange={(e) => patch({ from: e.target.value })}
                className={segmentInput}
              />
            </label>
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label="Swap origin and destination"
              onClick={() => patch({ from: value.to, to: value.from })}
              className="mr-3 shrink-0 rounded-full lg:absolute lg:right-0 lg:z-10 lg:mr-0 lg:translate-x-1/2"
            >
              <ArrowLeftRight aria-hidden />
            </Button>
          </div>

          <label
            htmlFor={`${id}-to`}
            className="flex min-w-0 flex-1 flex-col gap-0.5 px-5 py-3 focus-within:bg-muted/50 lg:pl-8"
          >
            <span className={segmentLabel}>To</span>
            <Input
              id={`${id}-to`}
              autoComplete="off"
              placeholder="City or airport"
              value={value.to}
              onChange={(e) => patch({ to: e.target.value })}
              className={segmentInput}
            />
          </label>

          <DatesSegment value={value} onChange={patch} idPrefix={id} />
        </div>

        <Button
          type="submit"
          size="lg"
          disabled={!complete}
          className="h-12 gap-2 rounded-full px-7 text-base font-semibold shadow-md"
        >
          <Search aria-hidden />
          Search
        </Button>
      </div>

      <div className="flex flex-wrap items-center justify-center gap-1 rounded-full bg-background/80 px-2 py-1 shadow-sm ring-1 ring-foreground/5 backdrop-blur-md">
        <Select
          items={TRIP_TYPES}
          value={value.tripType}
          onValueChange={(v) => {
            if (!v) return
            patch({
              tripType: v as TripType,
              returnDate: v === "one-way" ? undefined : value.returnDate,
            })
          }}
        >
          <SelectTrigger aria-label="Trip type" className={pillTrigger}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent alignItemWithTrigger={false} className="min-w-44">
            {TRIP_TYPES.map((t) => (
              <SelectItem key={t.value} value={t.value}>
                {t.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Passengers
          value={value.passengers}
          onChange={(passengers) => patch({ passengers })}
        />

        <Select
          items={CABINS}
          value={value.cabin}
          onValueChange={(v) => v && patch({ cabin: v as Cabin })}
        >
          <SelectTrigger aria-label="Cabin class" className={pillTrigger}>
            <Armchair aria-hidden />
            <SelectValue />
          </SelectTrigger>
          <SelectContent alignItemWithTrigger={false} className="min-w-48">
            {CABINS.map((c) => (
              <SelectItem key={c.value} value={c.value}>
                {c.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </form>
  )
}
