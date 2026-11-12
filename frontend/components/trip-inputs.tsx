"use client"

import * as React from "react"
import {
  ArrowRight,
  Bus,
  CalendarIcon,
  Check,
  ChevronDown,
  Clock,
  Plane,
  Ship,
  SlidersHorizontal,
  TrainFront,
  X,
  type LucideIcon,
} from "lucide-react"

import { CityPicker, type City } from "@/components/city-picker"
import { Button } from "@/components/ui/button"
import { Calendar } from "@/components/ui/calendar"
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@/components/ui/combobox"
import { Label } from "@/components/ui/label"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import type { TransportType } from "@/generated/schema_v1"
import { cn } from "@/lib/utils"

export type TripInputsValue = {
  departure: City | null
  /** Total budget in EUR; empty string when unset. */
  budget: string
  date: Date | undefined
  /** Trip length in days (from the duration options); empty string when unset. */
  duration: string
  /** Allowed transport modes; at least one is required. */
  modes: TransportType[]
  /** Cities the trip must pass through. */
  mustVisit: City[]
  /** Cities the trip must not touch. */
  avoid: City[]
}

export const EMPTY_TRIP_INPUTS: TripInputsValue = {
  departure: null,
  budget: "",
  date: undefined,
  duration: "",
  modes: ["PLANES", "TRAINS", "BUSSES", "FERRIES"],
  mustVisit: [],
  avoid: [],
}

const MODE_OPTIONS: { value: TransportType; label: string; Icon: LucideIcon }[] = [
  { value: "PLANES", label: "Flight", Icon: Plane },
  { value: "TRAINS", label: "Train", Icon: TrainFront },
  { value: "BUSSES", label: "Bus", Icon: Bus },
  { value: "FERRIES", label: "Ferry", Icon: Ship },
]

const BUDGET_SUGGESTIONS = [250, 500, 750, 1000, 1500]

type DurationOption = { value: string; label: string }

const customOption = (days: string): DurationOption => ({
  value: days,
  label: `${days} ${days === "1" ? "day" : "days"}`,
})

/** `value` is the trip length in days. */
const DURATION_OPTIONS: DurationOption[] = ["2", "3", "5", "7", "14"].map(
  (days) => customOption(days)
)

const MAX_CUSTOM_DAYS = 365

/** The option for a stored day count: a preset, or a custom "N days". */
function optionForDays(days: string): DurationOption | null {
  if (!days) return null
  return DURATION_OPTIONS.find((o) => o.value === days) ?? customOption(days)
}

/** Options for the typed text; an integer yields a preset or custom option. */
function durationItems(query: string, selected: DurationOption | null) {
  const q = query.trim()
  if (!q || q === selected?.label) return DURATION_OPTIONS
  if (/^\d+$/.test(q)) {
    const days = String(Number(q))
    if (Number(days) < 1 || Number(days) > MAX_CUSTOM_DAYS) return []
    return [optionForDays(days)!]
  }
  const lower = q.toLowerCase()
  return DURATION_OPTIONS.filter((o) => o.label.toLowerCase().includes(lower))
}

const dateFormat = new Intl.DateTimeFormat("en-GB", { dateStyle: "medium" })

type TripInputsProps = {
  value: TripInputsValue
  onChange: (value: TripInputsValue) => void
  cities: City[]
  /** Called when the user presses "Find opportunities" with a complete form. */
  onSubmit?: (value: TripInputsValue) => void
  loading?: boolean
  className?: string
}

export function isTripInputsComplete(v: TripInputsValue) {
  return (
    v.departure !== null &&
    Number(v.budget) > 0 &&
    v.date !== undefined &&
    Number(v.duration) > 0 &&
    v.modes.length > 0
  )
}

const CARD = "rounded-[20px] border bg-card"
const CAPTION =
  "block text-[11px] font-bold tracking-wider text-muted-foreground uppercase"
const SECTION_TITLE =
  "text-[15px] font-extrabold tracking-wide text-teal uppercase"

function FieldShell({
  icon: Icon,
  invalid,
  children,
}: {
  icon: LucideIcon
  invalid?: boolean
  children: React.ReactNode
}) {
  return (
    <div
      className={cn(
        CARD,
        "flex min-h-[84px] items-center gap-3.5 px-4 py-3 transition-colors focus-within:border-teal/60",
        invalid && "border-red-400"
      )}
    >
      <span className="grid size-10 shrink-0 place-items-center rounded-full bg-mint">
        <Icon className="size-5 text-teal" />
      </span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}

function Tick({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "grid size-6 shrink-0 place-items-center rounded-full bg-forest",
        className
      )}
    >
      <Check className="size-3.5 text-white" strokeWidth={3} />
    </span>
  )
}

function CityChips({
  cities,
  onRemove,
}: {
  cities: City[]
  onRemove: (city: City) => void
}) {
  if (cities.length === 0) return null
  return (
    <ul className="mt-2 flex flex-wrap gap-2">
      {cities.map((c) => (
        <li
          key={c.id}
          className="inline-flex items-center gap-1 rounded-full bg-mint py-1 pr-1.5 pl-3 text-sm font-semibold"
        >
          {c.name}
          <button
            type="button"
            aria-label={`Remove ${c.name}`}
            onClick={() => onRemove(c)}
            className="grid size-5 place-items-center rounded-full hover:bg-white"
          >
            <X className="size-3" />
          </button>
        </li>
      ))}
    </ul>
  )
}

function MultiCityField({
  label,
  placeholder,
  selected,
  onChange,
  cities,
  exclude,
}: {
  label: string
  placeholder: string
  selected: City[]
  onChange: (cities: City[]) => void
  cities: City[]
  /** Cities that can't be picked here (already used elsewhere). */
  exclude: City[]
}) {
  const taken = new Set([...selected, ...exclude].map((c) => c.id))
  return (
    <div>
      <CityPicker
        label={label}
        placeholder={placeholder}
        value={null}
        onChange={(c) => c && onChange([...selected, c])}
        cities={cities.filter((c) => !taken.has(c.id))}
      />
      <CityChips
        cities={selected}
        onRemove={(c) => onChange(selected.filter((x) => x.id !== c.id))}
      />
    </div>
  )
}

export function TripInputs({
  value,
  onChange,
  cities,
  onSubmit,
  loading = false,
  className,
}: TripInputsProps) {
  const id = React.useId()
  const [dateOpen, setDateOpen] = React.useState(false)
  const [advancedOpen, setAdvancedOpen] = React.useState(false)
  const selectedDuration = optionForDays(value.duration)
  const [durationQuery, setDurationQuery] = React.useState(
    selectedDuration?.label ?? ""
  )
  const [today, setToday] = React.useState<Date>()

  const set = <K extends keyof TripInputsValue>(key: K, v: TripInputsValue[K]) =>
    onChange({ ...value, [key]: v })

  const toggleMode = (mode: TransportType) =>
    set(
      "modes",
      value.modes.includes(mode)
        ? value.modes.filter((m) => m !== mode)
        : [...value.modes, mode]
    )

  const budget = (
    <section
      aria-labelledby={`${id}-budget-title`}
      className={cn(CARD, "p-5 sm:p-6")}
    >
      <h2 id={`${id}-budget-title`} className={SECTION_TITLE}>
        Your budget
      </h2>
      <p className="mt-1.5 text-sm text-muted-foreground">
        Maximum total price per traveller, including taxes and fees.
      </p>
      <label htmlFor={`${id}-budget`} className="mt-5 mb-2 block text-sm font-semibold">
        Maximum budget
      </label>
      <div className="flex h-[60px] max-w-[380px] items-center gap-3 rounded-2xl border border-teal/60 bg-card px-5 focus-within:ring-4 focus-within:ring-mint">
        <span className="text-lg font-bold">€</span>
        <input
          id={`${id}-budget`}
          type="text"
          inputMode="numeric"
          autoComplete="off"
          placeholder="Amount"
          value={value.budget}
          onChange={(e) =>
            set(
              "budget",
              e.target.value.replace(/\D/g, "").replace(/^0+/, "").slice(0, 7)
            )
          }
          className="min-w-0 flex-1 bg-transparent text-[22px] font-bold outline-none placeholder:text-muted-foreground/70"
        />
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {BUDGET_SUGGESTIONS.map((n) => (
          <button
            key={n}
            type="button"
            aria-pressed={value.budget === String(n)}
            onClick={() => set("budget", String(n))}
            className={cn(
              "rounded-full border px-3.5 py-1.5 text-sm font-semibold transition-colors hover:bg-mint",
              value.budget === String(n) && "border-teal/70 bg-sel text-teal"
            )}
          >
            €{n.toLocaleString("en-GB")}
          </button>
        ))}
      </div>
    </section>
  )

  const transport = (
    <section
      aria-labelledby={`${id}-transport-title`}
      className={cn(CARD, "p-5 sm:p-6")}
    >
      <h2 id={`${id}-transport-title`} className={SECTION_TITLE}>
        How would you like to travel?
      </h2>
      <p className="mt-1.5 text-sm text-muted-foreground">
        Choose one or more transport options.
      </p>
      <div
        role="group"
        aria-label="Transport"
        className="mt-4 grid grid-cols-2 gap-2.5 sm:grid-cols-4 sm:gap-3"
      >
        {MODE_OPTIONS.map(({ value: mode, label, Icon }) => {
          const on = value.modes.includes(mode)
          return (
            <button
              key={mode}
              type="button"
              role="checkbox"
              aria-checked={on}
              onClick={() => toggleMode(mode)}
              className={cn(
                "relative flex min-h-[112px] cursor-pointer flex-col items-center justify-center gap-2.5 rounded-2xl border font-bold transition-all select-none hover:shadow-sm active:scale-[0.97]",
                on ? "border-teal/70 bg-sel" : "bg-card hover:border-teal/40"
              )}
            >
              {on && <Tick className="absolute top-2 right-2 size-[22px]" />}
              <Icon className="size-8 text-forest" strokeWidth={1.6} />
              {label}
            </button>
          )
        })}
      </div>
      {value.modes.length === 0 && (
        <p role="alert" className="mt-2 text-[13px] text-red-700">
          Choose at least one way to travel.
        </p>
      )}
    </section>
  )

  return (
    <form
      aria-label="Trip details"
      onSubmit={(e) => {
        e.preventDefault()
        if (isTripInputsComplete(value) && !loading) onSubmit?.(value)
      }}
      className={cn("space-y-4", className)}
    >
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[1.25fr_1fr_1fr]">
        <CityPicker
          variant="card"
          label="Round trip from"
          helper="Leave and return to the same place."
          placeholder="City"
          value={value.departure}
          onChange={(c) => set("departure", c)}
          cities={cities}
        />

        <Popover
          open={dateOpen}
          onOpenChange={(open) => {
            if (open) setToday(new Date())
            setDateOpen(open)
          }}
        >
          <FieldShell icon={CalendarIcon}>
            <Label htmlFor={`${id}-date`} className={CAPTION}>
              When
            </Label>
            <PopoverTrigger
              render={
                <button
                  id={`${id}-date`}
                  type="button"
                  className={cn(
                    "flex w-full items-center justify-between text-left text-xl font-bold",
                    !value.date && "text-muted-foreground"
                  )}
                />
              }
            >
              {value.date ? dateFormat.format(value.date) : "Pick a date"}
              <ChevronDown className="size-4 text-foreground" />
            </PopoverTrigger>
          </FieldShell>
          <PopoverContent align="start" className="w-auto p-0">
            <Calendar
              mode="single"
              selected={value.date}
              onSelect={(d) => {
                set("date", d)
                setDateOpen(false)
              }}
              disabled={today ? { before: today } : undefined}
              autoFocus
            />
          </PopoverContent>
        </Popover>

        <FieldShell icon={Clock}>
          <Label htmlFor={`${id}-duration`} className={CAPTION}>
            Trip length
          </Label>
          <Combobox
            items={durationItems(durationQuery, selectedDuration)}
            filter={null}
            autoHighlight
            value={selectedDuration}
            onValueChange={(o) => set("duration", o?.value ?? "")}
            inputValue={durationQuery}
            onInputValueChange={setDurationQuery}
            isItemEqualToValue={(a, b) => a.value === b.value}
          >
            <ComboboxInput
              id={`${id}-duration`}
              placeholder="Days"
              className="h-auto border-0 bg-transparent has-[[data-slot=input-group-control]:focus-visible]:ring-0 dark:bg-transparent [&_input]:h-auto [&_input]:px-0 [&_input]:text-xl [&_input]:font-bold [&_input]:md:text-xl"
            />
            <ComboboxContent>
              <ComboboxEmpty>Enter a whole number of days (1–365)</ComboboxEmpty>
              <ComboboxList>
                {(item: DurationOption) => (
                  <ComboboxItem key={item.value} value={item}>
                    {item.label}
                  </ComboboxItem>
                )}
              </ComboboxList>
            </ComboboxContent>
          </Combobox>
        </FieldShell>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {budget}
        {transport}
      </div>

      <section className={CARD}>
        <button
          type="button"
          aria-expanded={advancedOpen}
          aria-controls={`${id}-advanced`}
          onClick={() => setAdvancedOpen((o) => !o)}
          className="flex w-full items-center gap-3 rounded-[20px] px-5 py-4 text-left sm:px-6"
        >
          <SlidersHorizontal className="size-5 text-teal" />
          <span className="flex-1 text-[17px] font-bold">Advanced search</span>
          <ChevronDown
            className={cn(
              "size-5 transition-transform duration-300",
              advancedOpen && "rotate-180"
            )}
          />
        </button>
        {advancedOpen && (
          <div
            id={`${id}-advanced`}
            className="grid gap-5 px-5 pt-1 pb-6 sm:px-6 md:grid-cols-2"
          >
            <MultiCityField
              label="Must-visit cities"
              placeholder="e.g. Prague"
              selected={value.mustVisit}
              onChange={(c) => set("mustVisit", c)}
              cities={cities}
              exclude={[
                ...value.avoid,
                ...(value.departure ? [value.departure] : []),
              ]}
            />
            <MultiCityField
              label="Avoid cities"
              placeholder="e.g. Paris"
              selected={value.avoid}
              onChange={(c) => set("avoid", c)}
              cities={cities}
              exclude={[
                ...value.mustVisit,
                ...(value.departure ? [value.departure] : []),
              ]}
            />
          </div>
        )}
      </section>

      <Button
        type="submit"
        size="lg"
        disabled={!isTripInputsComplete(value) || loading}
        className="h-16 w-full rounded-[18px] text-xl font-bold hover:bg-deep hover:shadow-lg"
      >
        {loading ? "Searching…" : "Find my trip"}
        {!loading && <ArrowRight className="size-5" />}
      </Button>
    </form>
  )
}
