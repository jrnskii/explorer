"use client"

import * as React from "react"
import {
  Bus,
  CalendarIcon,
  ChevronDown,
  CircleHelp,
  Plane,
  Search,
  // Ship,
  SlidersHorizontal,
  TrainFront,
  X,
  type LucideIcon,
} from "lucide-react"

import { CityPicker, type City } from "@/components/city-picker"
import {
  SEARCH_CONTROL,
  SearchBar,
  SearchSegment,
} from "@/components/search-bar"
// import { TravelerPicker } from "@/components/traveler-picker"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
// import { Checkbox } from "@/components/ui/checkbox"
import { Calendar } from "@/components/ui/calendar"
import {
  Card,
  CardContent,
} from "@/components/ui/card"
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@/components/ui/combobox"
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
  InputGroupText,
} from "@/components/ui/input-group"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { Field, FieldLabel } from "@/components/ui/field"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import type { TransportType } from "@/generated/schema_v1"
import { cn } from "@/lib/utils"

export type TripInputsValue = {
  departure: City | null
  /** Total budget in EUR; empty string when unset. */
  budget: string
  date: Date | undefined
  /** Trip length in days or a "from-to" range (from the duration options); empty string when unset. */
  duration: string
  /** Whether the user can shift the trip dates. */
  flexibleDates: boolean
  /** Number of travellers. */
  travelers: number
  /** Allowed transport modes; at least one is required. */
  modes: TransportType[]
  /** Number of cities to visit; empty string when unset. */
  numberOfCities: string
  /** Return date; must not be before `date`. */
  returnDate: Date | undefined
  /** Days to spend in each city; empty string when unset. */
  daysPerCity: string
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
  flexibleDates: false,
  travelers: 1,
  modes: ["PLANES", "TRAINS", "BUSSES" /* , "FERRIES" */],
  numberOfCities: "",
  returnDate: undefined,
  daysPerCity: "",
  mustVisit: [],
  avoid: [],
}

const MODE_OPTIONS: {
  value: TransportType
  label: string
  Icon: LucideIcon
}[] = [
  { value: "PLANES", label: "Flight", Icon: Plane },
  { value: "TRAINS", label: "Train", Icon: TrainFront },
  { value: "BUSSES", label: "Bus", Icon: Bus },
  // { value: "FERRIES", label: "Ferry", Icon: Ship },
]

type DurationOption = { value: string; label: string }

const customOption = (days: string): DurationOption => ({
  value: days,
  label: `${days} ${days === "1" ? "day" : "days"}`,
})

const rangeOption = (from: number, to: number): DurationOption => ({
  value: `${from}-${to}`,
  label: `${from}-${to} days`,
})

/** Max digits in the budget field (up to 9999). */
const MAX_BUDGET_DIGITS = 4

/** Budget suggestions in EUR: 50 to 300 in steps of 50. */
const BUDGET_SUGGESTIONS = Array.from({ length: 6 }, (_, i) =>
  String((i + 1) * 50)
)

/** Picking this clears the field so a number of days can be typed. */
const CUSTOM_DURATION: DurationOption = {
  value: "custom",
  label: "Custom duration",
}

/** `value` is the trip length in days, or a "from-to" range of days. */
const DURATION_OPTIONS: DurationOption[] = [
  ...["2", "3", "5", "7"].map(customOption),
  rangeOption(8, 14),
  rangeOption(15, 21),
  rangeOption(22, 30),
  CUSTOM_DURATION,
]

const MAX_CUSTOM_DAYS = 365

/** The option for a stored duration: a preset, range, or custom "N days". */
function optionForDays(days: string): DurationOption | null {
  if (!days) return null
  return DURATION_OPTIONS.find((o) => o.value === days) ?? customOption(days)
}

/** Whether a stored duration is a day count or a preset range. */
function isValidDuration(duration: string) {
  return Number(duration) > 0 || /^\d+-\d+$/.test(duration)
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
  /** Async departure search (e.g. all European cities); falls back to `cities`. */
  onSearchDeparture?: (query: string, signal: AbortSignal) => Promise<City[]>
  /** Departure suggestions shown before the user types. */
  departureSuggestions?: City[]
  /** Called when the user presses "Find opportunities" with a complete form. */
  onSubmit?: (value: TripInputsValue) => void
  /** Called instead of `onSubmit` for trips longer than 7 days, which require an account. */
  onSignUp?: (value: TripInputsValue) => void
  loading?: boolean
  className?: string
}

export function isTripInputsComplete(v: TripInputsValue) {
  return (
    v.departure !== null &&
    Number(v.budget) > 0 &&
    v.date !== undefined &&
    isValidDuration(v.duration) &&
    v.modes.length > 0
  )
}

/** Digits-only text field with a unit suffix, e.g. "3 cities". */
function NumberField({
  id,
  label,
  unit,
  placeholder,
  maxDigits,
  value,
  onChange,
}: {
  id: string
  label: string
  unit: string
  placeholder: string
  maxDigits: number
  value: string
  onChange: (value: string) => void
}) {
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <InputGroup>
        <InputGroupInput
          id={id}
          type="text"
          inputMode="numeric"
          autoComplete="off"
          placeholder={placeholder}
          value={value}
          onChange={(e) =>
            onChange(
              e.target.value
                .replace(/\D/g, "")
                .replace(/^0+/, "")
                .slice(0, maxDigits)
            )
          }
        />
        <InputGroupAddon align="inline-end">
          <InputGroupText>{unit}</InputGroupText>
        </InputGroupAddon>
      </InputGroup>
    </Field>
  )
}

/** Outline-button date picker in a popover. */
function DateField({
  id,
  label,
  value,
  onChange,
  disabledBefore,
}: {
  id: string
  label: string
  value: Date | undefined
  onChange: (value: Date | undefined) => void
  /** Dates before this are not selectable. */
  disabledBefore?: Date
}) {
  const [open, setOpen] = React.useState(false)
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger
          render={
            <Button
              id={id}
              type="button"
              variant="outline"
              className={cn(
                "w-full justify-between font-normal",
                !value && "text-muted-foreground"
              )}
            />
          }
        >
          {value ? dateFormat.format(value) : "Pick a date"}
          <CalendarIcon />
        </PopoverTrigger>
        <PopoverContent align="start" className="w-auto p-0">
          <Calendar
            mode="single"
            selected={value}
            defaultMonth={value ?? disabledBefore}
            onSelect={(d) => {
              onChange(d)
              setOpen(false)
            }}
            disabled={disabledBefore ? { before: disabledBefore } : undefined}
            autoFocus
          />
        </PopoverContent>
      </Popover>
    </Field>
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
    <ul className="flex flex-wrap gap-2">
      {cities.map((c) => (
        <li key={c.id}>
          <Badge variant="secondary">
            {c.name}
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              aria-label={`Remove ${c.name}`}
              onClick={() => onRemove(c)}
            >
              <X />
            </Button>
          </Badge>
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
    <div className="flex flex-col gap-2">
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
  onSearchDeparture,
  departureSuggestions,
  onSubmit,
  onSignUp,
  loading = false,
  className,
}: TripInputsProps) {
  const id = React.useId()
  const [dateOpen, setDateOpen] = React.useState(false)
  const selectedDuration = optionForDays(value.duration)
  const [durationQuery, setDurationQuery] = React.useState(
    selectedDuration?.label ?? ""
  )
  const durationInput = React.useRef<HTMLInputElement>(null)
  const [today, setToday] = React.useState<Date>()

  const set = <K extends keyof TripInputsValue>(
    key: K,
    v: TripInputsValue[K]
  ) => onChange({ ...value, [key]: v })

  /** Trips longer than 7 days (ranges and custom counts) require signing up. */
  const requiresSignUp = parseInt(value.duration) > 7

  return (
    <form
      aria-label="Trip details"
      onSubmit={(e) => {
        e.preventDefault()
        if (!isTripInputsComplete(value) || loading) return
        if (requiresSignUp) onSignUp?.(value)
        else onSubmit?.(value)
      }}
      className={cn("flex flex-col gap-4", className)}
    >
      <SearchBar className="divide-y-0 rounded-3xl lg:divide-x-0 lg:rounded-full">
        <SearchSegment
                  label="Departure"
                  htmlFor={`${id}-departure`}
                  className="px-6 py-5 lg:pl-9"
                >
          <CityPicker
            bare
            id={`${id}-departure`}
            inputClassName={SEARCH_CONTROL}
            placeholder="City"
            value={value.departure}
            onChange={(c) => set("departure", c)}
            cities={cities}
            onSearch={onSearchDeparture}
            suggestions={departureSuggestions}
          />
        </SearchSegment>

        <SearchSegment
                  label="When"
                  htmlFor={`${id}-date`}
                  className="px-6 py-5"
                >
          <Popover
            open={dateOpen}
            onOpenChange={(open) => {
              if (open) setToday(new Date())
              setDateOpen(open)
            }}
          >
            <PopoverTrigger
              render={
                <Button
                  id={`${id}-date`}
                  type="button"
                  variant="ghost"
                  className={cn(
                    "h-8 justify-between px-0 text-base font-semibold hover:bg-transparent aria-expanded:bg-transparent",
                    !value.date && "text-muted-foreground"
                  )}
                />
              }
            >
              {value.date ? dateFormat.format(value.date) : "Pick a date"}
              <CalendarIcon />
            </PopoverTrigger>
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
        </SearchSegment>

        <SearchSegment
                  label="Trip length"
                  htmlFor={`${id}-duration`}
                  className="px-6 py-5"
                >
          <Combobox
            items={durationItems(durationQuery, selectedDuration)}
            filter={null}
            autoHighlight
            value={selectedDuration}
            onValueChange={(o) => {
              if (o?.value === CUSTOM_DURATION.value) {
                set("duration", "")
                setDurationQuery("")
                requestAnimationFrame(() => durationInput.current?.focus())
                return
              }
              set("duration", o?.value ?? "")
            }}
            inputValue={durationQuery}
            onInputValueChange={(v) =>
              setDurationQuery(v === CUSTOM_DURATION.label ? "" : v)
            }
            isItemEqualToValue={(a, b) => a.value === b.value}
          >
            <ComboboxInput
              id={`${id}-duration`}
              ref={durationInput}
              placeholder="Days"
              className={SEARCH_CONTROL}
            />
            <ComboboxContent className="min-w-48">
              <ComboboxEmpty>Enter a whole number of days (1–365)</ComboboxEmpty>
              <ComboboxList>
                {(item: DurationOption) => (
                  <ComboboxItem
                    key={item.value}
                    value={item}
                    className={cn(
                      parseInt(item.value) > 7 && "text-muted-foreground"
                    )}
                  >
                    {item.label}
                  </ComboboxItem>
                )}
              </ComboboxList>
            </ComboboxContent>
          </Combobox>
        </SearchSegment>

        <TooltipProvider>
          <Tooltip disabled={value.modes.length > 0}>
            <TooltipTrigger
              render={
                <Button
                  type="submit"
                  size="lg"
                  focusableWhenDisabled={value.modes.length === 0}
                  disabled={!isTripInputsComplete(value) || loading}
                  className="m-1.5 h-14 w-[calc(100%-0.75rem)] self-center rounded-full border-0 px-10 text-lg font-bold aria-disabled:opacity-50 lg:h-auto lg:w-auto lg:shrink-0 lg:self-stretch [&_svg:not([class*='size-'])]:size-5"
                />
              }
            >
              {!loading && <Search aria-hidden />}
              {loading
                ? "Searching…"
                : requiresSignUp
                  ? "Sign up to continue"
                  : "Search"}
            </TooltipTrigger>
            <TooltipContent>
              Choose at least one way to travel.
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </SearchBar>


      <div className="flex flex-wrap items-center justify-center gap-x-6 gap-y-3">
        <div className="flex flex-wrap items-center justify-center gap-2">
          <span id={`${id}-modes`} className="sr-only">
            Travel by
          </span>
          <ToggleGroup
            multiple
            variant="outline"
            spacing={2}
            aria-labelledby={`${id}-modes`}
            value={value.modes}
            onValueChange={(v) => set("modes", v as TransportType[])}
            className="flex-wrap justify-center"
          >
            {MODE_OPTIONS.map(({ value: mode, label, Icon }) => (
              <ToggleGroupItem
                              key={mode}
                              value={mode}
                              className="w-36 rounded-full bg-card hover:bg-muted aria-pressed:border-primary aria-pressed:bg-primary aria-pressed:text-primary-foreground aria-pressed:hover:bg-primary/90 aria-pressed:hover:text-primary-foreground"
                            >
                <Icon />
                {label}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          {/* <TravelerPicker
            id={`${id}-travelers`}
            value={value.travelers}
            onChange={(n) => set("travelers", n)}
          /> */}
          <Combobox
            items={BUDGET_SUGGESTIONS}
            filter={null}
            value={
              BUDGET_SUGGESTIONS.includes(value.budget) ? value.budget : null
            }
            onValueChange={(v) => set("budget", v ?? "")}
            inputValue={value.budget}
            onInputValueChange={(v) =>
              set(
                "budget",
                v
                  .replace(/\D/g, "")
                  .replace(/^0+/, "")
                  .slice(0, MAX_BUDGET_DIGITS)
              )
            }
          >
            <ComboboxInput
              id={`${id}-budget`}
              aria-label="Max. budget"
              inputMode="numeric"
              autoComplete="off"
              placeholder="Max. budget"
              className={cn(
                              "h-8 w-36 rounded-full [&_input]:text-sm [&_input]:font-medium",
                              value.budget
                                ? "border-primary bg-primary text-primary-foreground dark:bg-primary [&_input]:text-primary-foreground"
                                : "bg-card dark:bg-card"
                            )}
                            showTrigger={false}
            >
              <InputGroupAddon>
                <InputGroupText
                  className={cn(
                    "font-medium",
                    value.budget ? "text-primary-foreground" : "text-foreground"
                  )}
                >
                  €
                </InputGroupText>
              </InputGroupAddon>
            </ComboboxInput>
            <ComboboxContent className="min-w-32">
              <ComboboxList>
                {(item: string) => (
                  <ComboboxItem key={item} value={item}>
                    €{item}
                  </ComboboxItem>
                )}
              </ComboboxList>
            </ComboboxContent>
          </Combobox>
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button
                    type="button"
                    size="icon"
                    className="rounded-full text-white"
                    aria-label="About sample itineraries"
                  />
                }
              >
                <CircleHelp aria-hidden />
              </TooltipTrigger>
              <TooltipContent className="text-sm leading-relaxed">
                Sample itineraries with estimated fares. Schedules are illustrative, not bookable. Routes without supported pricing are omitted.
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>

        {/* <Field
                  orientation="horizontal"
                  className="ml-auto h-8 w-auto items-center rounded-full border border-input bg-card px-3"
                >
          <Checkbox
            id={`${id}-flexible`}
            checked={value.flexibleDates}
            onCheckedChange={(checked) => set("flexibleDates", checked)}
          />
          <FieldLabel htmlFor={`${id}-flexible`} className="font-normal">
            I&apos;m flexible with travel dates
          </FieldLabel>
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  aria-label="About flexible dates"
                />
              }
            >
              <Info />
            </TooltipTrigger>
            <TooltipContent side="left" className="max-w-xs">
              Explorer will search up to 2 days before and 2 days after your
              selected departure date to find more affordable journeys.
            </TooltipContent>
          </Tooltip>
        </Field> */}
      </div>

      {/* Advanced search section (temporarily disabled)
      <Collapsible className="flex flex-col gap-4">
        <CollapsibleTrigger
          render={<Button type="button" variant="ghost" className="self-start" />}
        >
          <SlidersHorizontal />
          Advanced search
          <ChevronDown />
        </CollapsibleTrigger>
        <CollapsibleContent>
          <Card>
            <CardContent className="flex flex-col gap-6">
              <div className="grid gap-4 md:grid-cols-3">
                <NumberField
                  id={`${id}-city-count`}
                  label="Number of cities"
                  unit="cities"
                  placeholder="Any"
                  maxDigits={2}
                  value={value.numberOfCities}
                  onChange={(v) => set("numberOfCities", v)}
                />
                <DateField
                  id={`${id}-return-date`}
                  label="Return date"
                  value={value.returnDate}
                  onChange={(d) => set("returnDate", d)}
                  disabledBefore={value.date ?? today}
                />
                <NumberField
                  id={`${id}-days-per-city`}
                  label="Time per city"
                  unit="days"
                  placeholder="Any"
                  maxDigits={3}
                  value={value.daysPerCity}
                  onChange={(v) => set("daysPerCity", v)}
                />
              </div>
              <div className="grid gap-4 md:grid-cols-2">
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
            </CardContent>
          </Card>
        </CollapsibleContent>
      </Collapsible>
      */}
    </form>
  )
}
