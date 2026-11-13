import * as React from "react"

import { Card } from "@/components/ui/card"
import { Field, FieldLabel } from "@/components/ui/field"
import { cn } from "@/lib/utils"

/** Strips the border/ring from a shadcn input group so it blends into a segment. */
export const SEARCH_CONTROL =
  "h-8 border-0 bg-transparent shadow-none dark:bg-transparent has-[[data-slot=input-group-control]:focus-visible]:ring-0 [&_input]:px-0 [&_input]:text-base [&_input]:font-semibold [&_input]:md:text-base"

/** Skyscanner-style search bar: segments in one row on desktop, stacked on mobile. */
export function SearchBar({
  className,
  ...props
}: React.ComponentProps<typeof Card>) {
  return (
    <Card
      data-slot="search-bar"
      className={cn(
        "flex-col gap-0 divide-y py-0 lg:flex-row lg:items-stretch lg:divide-x lg:divide-y-0",
        className
      )}
      {...props}
    />
  )
}

export function SearchSegment({
  label,
  htmlFor,
  className,
  children,
}: {
  label: string
  htmlFor?: string
  className?: string
  children: React.ReactNode
}) {
  return (
    <Field
      data-slot="search-segment"
      className={cn(
        "min-w-0 flex-1 gap-0.5 px-4 py-3 focus-within:bg-muted/50",
        className
      )}
    >
      <FieldLabel
        htmlFor={htmlFor}
        className="text-xs font-normal text-muted-foreground"
      >
        {label}
      </FieldLabel>
      {children}
    </Field>
  )
}

/** Wrapper for the submit button so it gets padding inside the bar. */
export function SearchBarAction({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="search-bar-action"
      className={cn("flex items-center p-3 lg:shrink-0", className)}
      {...props}
    />
  )
}
