"use client"

import { useId, useState, useSyncExternalStore } from "react"
import { Palette, RotateCcw } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover"
import { normalizeHex } from "@/lib/color"
import { DEFAULT_PRIMARY } from "@/lib/theme"
import {
  applyPrimary,
  readStoredPrimary,
  resetPrimary,
  subscribeToTheme,
} from "@/lib/theme-client"
import { cn } from "@/lib/utils"

export const PRESETS: { name: string; value: string }[] = [
  { name: "Forest", value: DEFAULT_PRIMARY },
  { name: "Ocean", value: "#2f6f8f" },
  { name: "Indigo", value: "#4452b8" },
  { name: "Plum", value: "#7a3e8e" },
  { name: "Rose", value: "#b0365a" },
  { name: "Amber", value: "#a9570f" },
]

const getServerPrimary = () => DEFAULT_PRIMARY

export function ThemePicker({ className }: { className?: string }) {
  const primary = useSyncExternalStore(subscribeToTheme, readStoredPrimary, getServerPrimary)
  const inputId = useId()
  const errorId = useId()
  // `null` means the text field mirrors the applied color; a string is an in-progress edit.
  const [draft, setDraft] = useState<string | null>(null)

  const text = draft ?? primary
  const invalid = draft !== null && normalizeHex(draft) === null

  function handleTextChange(value: string) {
    setDraft(value)
    if (normalizeHex(value)) applyPrimary(value)
  }

  return (
    <Popover onOpenChange={() => setDraft(null)}>
      <PopoverTrigger
        render={
          <Button
            type="button"
            variant="ghost"
            aria-label={`Theme color, currently ${primary}`}
            className={cn("text-foreground hover:bg-hover hover:text-forest", className)}
          />
        }
      >
        <Palette aria-hidden strokeWidth={1.5} />
        <span
          aria-hidden
          className="size-3.5 rounded-full border border-border"
          style={{ backgroundColor: primary }}
        />
      </PopoverTrigger>
      <PopoverContent align="end" sideOffset={8} className="w-72 gap-4 p-4">
        <PopoverHeader>
          <PopoverTitle>Theme color</PopoverTitle>
          <PopoverDescription>
            Pick a primary color. All other colors are derived from it.
          </PopoverDescription>
        </PopoverHeader>

        <div role="group" aria-label="Preset colors" className="flex flex-wrap gap-2">
          {PRESETS.map((preset) => {
            const selected = preset.value === primary
            return (
              <button
                key={preset.value}
                type="button"
                aria-label={preset.name}
                aria-pressed={selected}
                onClick={() => {
                  setDraft(null)
                  applyPrimary(preset.value)
                }}
                style={{ backgroundColor: preset.value }}
                className={cn(
                  "size-8 rounded-full border border-border outline-none transition-shadow focus-visible:ring-3 focus-visible:ring-ring/50",
                  selected && "ring-2 ring-foreground ring-offset-2 ring-offset-popover"
                )}
              />
            )
          })}
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor={inputId}>Custom color</Label>
          <div className="flex items-center gap-2">
            <input
              type="color"
              aria-label="Choose custom color"
              value={primary}
              onChange={(event) => {
                setDraft(null)
                applyPrimary(event.target.value)
              }}
              className="size-8 shrink-0 cursor-pointer rounded-md border border-border bg-transparent p-0.5"
            />
            <Input
              id={inputId}
              value={text}
              onChange={(event) => handleTextChange(event.target.value)}
              spellCheck={false}
              autoComplete="off"
              maxLength={7}
              aria-invalid={invalid || undefined}
              aria-describedby={invalid ? errorId : undefined}
              className="font-mono"
            />
          </div>
          {invalid ? (
            <p id={errorId} role="alert" className="text-xs text-destructive">
              Enter a hex color such as #345c49.
            </p>
          ) : null}
        </div>

        <Button
          type="button"
          variant="outline"
          disabled={primary === DEFAULT_PRIMARY}
          onClick={() => {
            setDraft(null)
            resetPrimary()
          }}
        >
          <RotateCcw aria-hidden strokeWidth={1.5} />
          Reset to default
        </Button>
      </PopoverContent>
    </Popover>
  )
}
