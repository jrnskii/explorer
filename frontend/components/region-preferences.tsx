"use client"

import * as React from "react"
import { Globe } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { lookupIpOrigin } from "@/lib/ip-origin"
import { currencyForCountry, parseCountryCode } from "@/lib/region"
import { cn } from "@/lib/utils"

type DetectedRegion = { country: string | null; currency: string | null }

/** Edge geo headers via /api/geo first; falls back to a public IP lookup. */
async function detectRegion(signal: AbortSignal): Promise<DetectedRegion | null> {
  try {
    const res = await fetch("/api/geo", { signal })
    if (res.ok) {
      const geo = (await res.json()) as DetectedRegion
      if (geo.country) return geo
    }
  } catch {
    if (signal.aborted) return null
  }
  const origin = await lookupIpOrigin(signal)
  if (!origin) return null
  const country = parseCountryCode(origin.countryCode)
  return country ? { country, currency: currencyForCountry(country) } : null
}

export type RegionOption = { value: string; label: string }

export type RegionPreferencesValue = {
  /** ISO 3166-1 alpha-2 country/region code. */
  country: string
  /** ISO 4217 currency code. */
  currency: string
}

export const COUNTRY_OPTIONS: RegionOption[] = [
  { value: "GB", label: "United Kingdom" },
  { value: "IE", label: "Ireland" },
  { value: "FR", label: "France" },
  { value: "DE", label: "Germany" },
  { value: "ES", label: "Spain" },
  { value: "IT", label: "Italy" },
  { value: "NL", label: "Netherlands" },
  { value: "LT", label: "Lithuania" },
  { value: "CZ", label: "Czechia" },
  { value: "PL", label: "Poland" },
  { value: "US", label: "United States" },
]

export const CURRENCY_OPTIONS: RegionOption[] = [
  { value: "EUR", label: "Euro (EUR)" },
  { value: "GBP", label: "Pound sterling (GBP)" },
  { value: "USD", label: "US dollar (USD)" },
  { value: "CZK", label: "Czech koruna (CZK)" },
  { value: "PLN", label: "Polish zloty (PLN)" },
]

export const DEFAULT_REGION_PREFERENCES: RegionPreferencesValue = {
  country: "GB",
  currency: "GBP",
}

type RegionPreferencesProps = {
  /** Initially applied preferences. */
  defaultValue?: RegionPreferencesValue
  /** Called with the chosen preferences when the user presses Apply. */
  onApply?: (value: RegionPreferencesValue) => void
  countries?: RegionOption[]
  currencies?: RegionOption[]
  /**
   * Fetch the visitor's country/currency from `/api/geo` on mount and apply
   * it, unless the user has already chosen something.
   */
  autoDetect?: boolean
  className?: string
}

/**
 * Header drop-down for choosing country/region and currency. The trigger is
 * labelled with the applied currency code. Choices are held
 * as a draft and only committed when "Apply" is pressed; closing the menu
 * discards the draft.
 */
export function RegionPreferences({
  defaultValue = DEFAULT_REGION_PREFERENCES,
  onApply,
  countries = COUNTRY_OPTIONS,
  currencies = CURRENCY_OPTIONS,
  autoDetect = false,
  className,
}: RegionPreferencesProps) {
  const id = React.useId()
  const countryId = `${id}-country`
  const currencyId = `${id}-currency`

  const [open, setOpen] = React.useState(false)
  const [applied, setApplied] = React.useState(defaultValue)
  const [draft, setDraft] = React.useState(defaultValue)

  const touched = React.useRef(false)

  React.useEffect(() => {
    if (!autoDetect) return
    const controller = new AbortController()
    detectRegion(controller.signal)
      .then((geo) => {
        if (!geo || touched.current) return
        const country = countries.some((o) => o.value === geo.country)
          ? geo.country
          : null
        const currency = currencies.some((o) => o.value === geo.currency)
          ? geo.currency
          : null
        if (!country && !currency) return
        const detected = {
          country: country ?? defaultValue.country,
          currency: currency ?? defaultValue.currency,
        }
        setApplied(detected)
        setDraft(detected)
      })
      .catch(() => {
        // Detection is best-effort; keep the defaults on failure.
      })
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once on mount
  }, [autoDetect])

  function handleOpenChange(next: boolean) {
    touched.current = true
    setOpen(next)
    if (next) setDraft(applied)
  }

  function handleApply() {
    setApplied(draft)
    onApply?.(draft)
    setOpen(false)
  }

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger
        render={
          <Button
            type="button"
            variant="ghost"
            aria-label={`Region preferences, currency ${applied.currency}`}
            className={cn("text-foreground hover:bg-hover hover:text-forest", className)}
          />
        }
      >
        <Globe aria-hidden strokeWidth={1.5} />
        {applied.currency}
      </PopoverTrigger>
      <PopoverContent align="end" sideOffset={8} className="w-80 gap-4 p-4">
        <PopoverHeader>
          <PopoverTitle>Region preferences</PopoverTitle>
          <PopoverDescription>
            Choose your country or region and the currency prices are shown in.
          </PopoverDescription>
        </PopoverHeader>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault()
            handleApply()
          }}
        >
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor={countryId}>Country/Region</FieldLabel>
              <Select
                items={countries}
                value={draft.country}
                onValueChange={(country) =>
                  country && setDraft((d) => ({ ...d, country }))
                }
              >
                <SelectTrigger id={countryId} className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent alignItemWithTrigger={false}>
                  {countries.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel htmlFor={currencyId}>Currency</FieldLabel>
              <Select
                items={currencies}
                value={draft.currency}
                onValueChange={(currency) =>
                  currency && setDraft((d) => ({ ...d, currency }))
                }
              >
                <SelectTrigger id={currencyId} className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent alignItemWithTrigger={false}>
                  {currencies.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          </FieldGroup>
          <Button type="submit" className="w-full">
            Apply
          </Button>
        </form>
      </PopoverContent>
    </Popover>
  )
}
