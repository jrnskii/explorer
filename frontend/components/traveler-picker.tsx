"use client"

import * as React from "react"
import { ChevronDown, Minus, Plus, Users } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { cn } from "@/lib/utils"

type TravelerPickerProps = {
  value: number
  onChange: (value: number) => void
  id?: string
  min?: number
  max?: number
  className?: string
}

const label = (n: number) => `${n} ${n === 1 ? "traveller" : "travellers"}`

/** Popover with a +/- stepper for the number of travellers. */
export function TravelerPicker({
  value,
  onChange,
  id,
  min = 1,
  max = 9,
  className,
}: TravelerPickerProps) {
  const generatedId = React.useId()
  const labelId = `${id ?? generatedId}-label`

  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button
            id={id}
            type="button"
            variant="ghost"
            className={cn(
              "h-8 w-full justify-between px-0 text-base font-semibold hover:bg-transparent aria-expanded:bg-transparent",
              className
            )}
          />
        }
      >
        <span className="flex items-center gap-2">
          <Users />
          {label(value)}
        </span>
        <ChevronDown />
      </PopoverTrigger>
      <PopoverContent align="end" sideOffset={12} className="w-72 gap-3">
        <div className="flex items-center justify-between gap-4">
          <div className="flex flex-col">
            <span id={labelId} className="text-sm font-medium">
              Travellers
            </span>
            <span className="text-xs text-muted-foreground">
              Up to {max} people
            </span>
          </div>
          <div
            role="group"
            aria-labelledby={labelId}
            className="flex items-center gap-3"
          >
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label="Remove a traveller"
              disabled={value <= min}
              onClick={() => onChange(Math.max(min, value - 1))}
            >
              <Minus />
            </Button>
            <output
              aria-live="polite"
              className="w-4 text-center text-base font-semibold tabular-nums"
            >
              {value}
            </output>
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label="Add a traveller"
              disabled={value >= max}
              onClick={() => onChange(Math.min(max, value + 1))}
            >
              <Plus />
            </Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  )
}
