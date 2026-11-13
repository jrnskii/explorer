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
import { cn } from "@/lib/utils"

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
  className,
}: RegionPreferencesProps) {
  const id = React.useId()
  const countryId = `${id}-country`
  const currencyId = `${id}-currency`

  const [open, setOpen] = React.useState(false)
  const [applied, setApplied] = React.useState(defaultValue)
  const [draft, setDraft] = React.useState(defaultValue)

  function handleOpenChange(next: boolean) {
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
