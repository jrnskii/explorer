"use client"

import * as React from "react"
import { MapPin } from "lucide-react"

import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@/components/ui/combobox"
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field"

export type City = {
  id: string
  name: string
  country: string
  /** Optional short code, e.g. "LON" */
  code?: string
}

type CityPickerProps = {
  /** Id for the input; generated when omitted. */
  id?: string
  value: City | null
  onChange: (city: City | null) => void
  /** Static list of cities, filtered locally. */
  cities?: City[]
  /** Async search (e.g. API call). Takes precedence over `cities`. */
  onSearch?: (query: string, signal: AbortSignal) => Promise<City[]>
  label?: string
  placeholder?: string
  /** Shown when the input is focused and empty. */
  suggestions?: City[]
  disabled?: boolean
  /** Classes for the input group (e.g. to blend into a search bar segment). */
  inputClassName?: string
  /** Renders just the input, without the Field wrapper and label. */
  bare?: boolean
  /** Small hint shown under the input. */
  helper?: string
  /** Marks the field as invalid. */
  invalid?: boolean
  className?: string
}

const format = (c: City) => `${c.name}, ${c.country}`

function matches(city: City, q: string) {
  const s = q.trim().toLowerCase()
  return (
    city.name.toLowerCase().includes(s) ||
    city.country.toLowerCase().includes(s) ||
    !!city.code?.toLowerCase().startsWith(s)
  )
}

export function CityPicker({
  id: idProp,
  value,
  onChange,
  cities = [],
  onSearch,
  label,
  placeholder = "Country, city or airport",
  suggestions,
  disabled,
  helper,
  inputClassName,
  bare,
  invalid,
  className,
}: CityPickerProps) {
  const generatedId = React.useId()
  const id = idProp ?? generatedId

  const [input, setInput] = React.useState(value ? format(value) : "")
  const [open, setOpen] = React.useState(false)
  const [remote, setRemote] = React.useState<City[]>([])
  const [loading, setLoading] = React.useState(false)

  // Keep the text in sync when the selection changes from outside.
  const [prevValue, setPrevValue] = React.useState(value)
  if (value !== prevValue) {
    setPrevValue(value)
    setInput(value ? format(value) : "")
  }

  // Text typed by the user; the selected city's label doesn't count as a query.
  const query = value && input === format(value) ? "" : input

  // Async search with debounce + cancellation
  React.useEffect(() => {
    if (!onSearch || !open || !query.trim()) return
    const controller = new AbortController()
    const timer = setTimeout(() => {
      setLoading(true)
      onSearch(query, controller.signal)
        .then((r) => !controller.signal.aborted && setRemote(r))
        .catch(() => !controller.signal.aborted && setRemote([]))
        .finally(() => !controller.signal.aborted && setLoading(false))
    }, 200)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [query, open, onSearch])

  const results = React.useMemo(() => {
    if (!query.trim()) return suggestions ?? cities.slice(0, 8)
    if (onSearch) return remote
    return cities.filter((c) => matches(c, query)).slice(0, 8)
  }, [query, suggestions, cities, onSearch, remote])

  const picker = (
    <Combobox
      items={results}
      filter={null}
      autoHighlight
      disabled={disabled}
      value={value}
      onValueChange={(city) => {
        onChange(city)
        // A controlled `value` re-syncs the text above; otherwise it stays cleared.
        setInput("")
      }}
      inputValue={input}
      onInputValueChange={(v, details) => {
        // Selecting an item is handled in onValueChange.
        if (details.reason === "item-press") return
        setInput(v)
      }}
      open={open}
      onOpenChange={setOpen}
      itemToStringValue={format}
      isItemEqualToValue={(a, b) => a.id === b.id}
    >
      <ComboboxInput
        id={id}
        placeholder={placeholder}
        aria-invalid={invalid || undefined}
        showClear={!!value && !disabled}
        className={inputClassName}
      />
      <ComboboxContent>
        <ComboboxEmpty>{loading ? "Searching…" : "No cities found"}</ComboboxEmpty>
        <ComboboxList>
          {(city: City) => (
            <ComboboxItem key={city.id} value={city}>
              <MapPin className="text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{city.name}</div>
                <div className="truncate text-xs text-muted-foreground">
                  {city.country}
                </div>
              </div>
              {city.code && (
                <span className="text-xs text-muted-foreground">{city.code}</span>
              )}
            </ComboboxItem>
          )}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  )

  if (bare) return picker

  return (
    <Field
      data-invalid={invalid}
      data-disabled={disabled || undefined}
      className={className}
    >
      {label && <FieldLabel htmlFor={id}>{label}</FieldLabel>}
      {picker}
      {helper && <FieldDescription>{helper}</FieldDescription>}
    </Field>
  )
}
