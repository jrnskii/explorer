"use client"

import * as React from "react"
import { MapPin, X } from "lucide-react"

import { cn } from "@/lib/utils"

export type City = {
  id: string
  name: string
  country: string
  /** Optional short code, e.g. "LON" */
  code?: string
}

type CityPickerProps = {
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
  /** "card" renders a large field card (icon bubble, caption label, big text). */
  variant?: "default" | "card"
  /** Small hint shown under the input in the card variant. */
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
  value,
  onChange,
  cities = [],
  onSearch,
  label,
  placeholder = "Country, city or airport",
  suggestions,
  disabled,
  variant = "default",
  helper,
  invalid,
  className,
}: CityPickerProps) {
  const card = variant === "card"
  const id = React.useId()
  const listId = `${id}-list`
  const rootRef = React.useRef<HTMLDivElement>(null)

  const [query, setQuery] = React.useState("")
  const [open, setOpen] = React.useState(false)
  const [active, setActive] = React.useState(0)
  const [remote, setRemote] = React.useState<City[]>([])
  const [loading, setLoading] = React.useState(false)

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

  // Close on outside click
  React.useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [])

  function select(city: City) {
    onChange(city)
    setQuery("")
    setOpen(false)
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault()
      setOpen(true)
      setActive((i) => Math.min(i + 1, results.length - 1))
    } else if (e.key === "ArrowUp") {
      e.preventDefault()
      setActive((i) => Math.max(i - 1, 0))
    } else if (e.key === "Enter" && open && results[active]) {
      e.preventDefault()
      select(results[active])
    } else if (e.key === "Escape") {
      setOpen(false)
    }
  }

  const showList = open && (results.length > 0 || loading || !!query.trim())

  const input = (
    <input
      id={id}
      role="combobox"
      aria-expanded={showList}
      aria-controls={listId}
      aria-autocomplete="list"
      aria-invalid={invalid || undefined}
      aria-activedescendant={
        showList && results[active] ? `${id}-${results[active].id}` : undefined
      }
      autoComplete="off"
      disabled={disabled}
      placeholder={placeholder}
      // While focused/typing show the query; otherwise the selected city
      value={open ? query : value ? format(value) : ""}
      onFocus={() => {
        setOpen(true)
        setActive(0)
      }}
      onChange={(e) => {
        setQuery(e.target.value)
        setOpen(true)
        setActive(0)
      }}
      onKeyDown={onKeyDown}
      className={cn(
        "min-w-0 flex-1 bg-transparent outline-none placeholder:text-muted-foreground",
        card ? "w-full truncate text-xl font-bold" : "text-sm"
      )}
    />
  )

  const clear = value && !disabled && (
    <button
      type="button"
      aria-label="Clear"
      onClick={() => {
        onChange(null)
        setQuery("")
      }}
      className="rounded p-1 text-muted-foreground hover:bg-muted"
    >
      <X className="size-4" />
    </button>
  )

  return (
    <div ref={rootRef} className={cn("relative w-full", className)}>
      {card ? (
        <div
          className={cn(
            "flex min-h-[84px] items-center gap-3.5 rounded-[20px] border bg-card px-4 py-3 transition-colors",
            "focus-within:border-teal/60",
            invalid && "border-red-400",
            disabled && "opacity-50"
          )}
        >
          <span className="grid size-10 shrink-0 place-items-center rounded-full bg-mint">
            <MapPin className="size-5 text-teal" />
          </span>
          <div className="min-w-0 flex-1">
            {label && (
              <label
                htmlFor={id}
                className="block text-[11px] font-bold tracking-wider text-muted-foreground uppercase"
              >
                {label}
              </label>
            )}
            <div className="flex items-center gap-1">
              {input}
              {clear}
            </div>
            {helper && (
              <div className="text-xs text-muted-foreground">{helper}</div>
            )}
          </div>
        </div>
      ) : (
        <>
          {label && (
            <label
              htmlFor={id}
              className="mb-1 block text-xs font-medium text-muted-foreground"
            >
              {label}
            </label>
          )}
          <div
            className={cn(
              "flex h-12 items-center gap-2 rounded-lg border bg-background px-3 transition-colors",
              "focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/30",
              disabled && "opacity-50"
            )}
          >
            <MapPin className="size-4 shrink-0 text-muted-foreground" />
            {input}
            {clear}
          </div>
        </>
      )}

      {showList && (
        <ul
          id={listId}
          role="listbox"
          className="absolute z-50 mt-1 max-h-72 w-full overflow-auto rounded-lg border bg-popover p-1 text-popover-foreground shadow-lg"
        >
          {!query.trim() && results.length > 0 && (
            <li className="px-3 py-1.5 text-xs font-medium text-muted-foreground">
              Suggestions
            </li>
          )}
          {results.map((city, i) => (
            <li
              key={city.id}
              id={`${id}-${city.id}`}
              role="option"
              aria-selected={value?.id === city.id}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => select(city)}
              className={cn(
                "flex cursor-pointer items-center gap-3 rounded-md px-3 py-2 text-sm",
                i === active && "bg-muted"
              )}
            >
              <MapPin className="size-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{city.name}</div>
                <div className="truncate text-xs text-muted-foreground">
                  {city.country}
                </div>
              </div>
              {city.code && (
                <span className="text-xs text-muted-foreground">{city.code}</span>
              )}
            </li>
          ))}
          {results.length === 0 && (
            <li className="px-3 py-2 text-sm text-muted-foreground">
              {loading ? "Searching…" : "No cities found"}
            </li>
          )}
        </ul>
      )}
    </div>
  )
}
