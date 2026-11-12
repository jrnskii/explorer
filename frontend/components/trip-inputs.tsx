"use client"

import * as React from "react"
import { CalendarIcon, Search, Wallet } from "lucide-react"

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
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { cn } from "@/lib/utils"

export type TripInputsValue = {
  departure: City | null
  /** Total budget in EUR; empty string when unset. */
  budget: string
  date: Date | undefined
  /** Trip length in days (from the duration options); empty string when unset. */
  duration: string
}

export const EMPTY_TRIP_INPUTS: TripInputsValue = {
  departure: null,
  budget: "",
  date: undefined,
  duration: "",
}

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
    Number(v.duration) > 0
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
  const selectedDuration = optionForDays(value.duration)
  const [durationQuery, setDurationQuery] = React.useState(
    selectedDuration?.label ?? ""
  )
  const [today, setToday] = React.useState<Date>()

  const set = <K extends keyof TripInputsValue>(key: K, v: TripInputsValue[K]) =>
    onChange({ ...value, [key]: v })

  return (
    <form
      aria-label="Trip details"
      onSubmit={(e) => {
        e.preventDefault()
        if (isTripInputsComplete(value) && !loading) onSubmit?.(value)
      }}
      className={cn(
        "grid gap-4 rounded-xl border bg-card p-4 text-card-foreground sm:grid-cols-2",
        className
      )}
    >
      <CityPicker
        label="Departure"
        value={value.departure}
        onChange={(c) => set("departure", c)}
        cities={cities}
      />

      <div className="flex flex-col gap-1">
        <Label htmlFor={`${id}-budget`} className="text-xs text-muted-foreground">
          Budget
        </Label>
        <div className="relative">
          <Wallet className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            id={`${id}-budget`}
            type="number"
            inputMode="numeric"
            min={0}
            step={50}
            placeholder="500"
            value={value.budget}
            onChange={(e) => set("budget", e.target.value)}
            className="h-12 pr-12 pl-9"
          />
          <span className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-sm text-muted-foreground">
            EUR
          </span>
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <Label htmlFor={`${id}-date`} className="text-xs text-muted-foreground">
          Trip date
        </Label>
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
                variant="outline"
                className={cn(
                  "h-12 w-full justify-start gap-2 px-3 font-normal",
                  !value.date && "text-muted-foreground"
                )}
              />
            }
          >
            <CalendarIcon className="size-4" />
            {value.date ? dateFormat.format(value.date) : "Pick a date"}
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
      </div>

      <div className="flex flex-col gap-1">
        <Label htmlFor={`${id}-duration`} className="text-xs text-muted-foreground">
          Trip duration
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
            placeholder="Pick or type number of days"
            className="h-12"
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
      </div>

      <Button
        type="submit"
        size="lg"
        disabled={!isTripInputsComplete(value) || loading}
        className="h-12 sm:col-span-2"
      >
        <Search className="size-4" />
        {loading ? "Searching…" : "Find opportunities"}
      </Button>
    </form>
  )
}
