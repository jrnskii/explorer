"use client"

import Image from "next/image"
import Link from "next/link"
import * as React from "react"
import { Building2, ChevronRight, Globe, Plane } from "lucide-react"

import {
  EMPTY_FLIGHT_SEARCH,
  FlightSearchForm,
  type FlightSearchValue,
} from "@/components/flight-search-form"
import { buttonVariants } from "@/components/ui/button"
import { cn } from "@/lib/utils"

const TABS = [
  { label: "Flights", icon: Plane, current: true },
  { label: "Stays", icon: Building2, current: false },
  { label: "Explore", icon: Globe, current: false },
] as const

/** Soft layered gradients that read as a cloudy sky; theme-aware via tokens. */
const SKY =
  "radial-gradient(60% 40% at 20% 85%, var(--cloud) 0%, transparent 70%), radial-gradient(55% 45% at 75% 80%, var(--cloud) 0%, transparent 70%), radial-gradient(70% 35% at 50% 60%, color-mix(in srgb, var(--sky) 55%, transparent) 0%, transparent 75%), linear-gradient(to bottom, var(--background) 0%, color-mix(in srgb, var(--sky) 45%, var(--background)) 50%, var(--cloud) 100%)"

export function FlightsHome() {
  const [search, setSearch] = React.useState<FlightSearchValue>(
    EMPTY_FLIGHT_SEARCH
  )

  return (
    <div
      className="relative flex min-h-screen flex-1 flex-col [--cloud:white] [--sky:#8fb4ee] dark:[--cloud:var(--background)] dark:[--sky:#1e3a8a]"
      style={{ background: SKY }}
    >
      <header className="relative z-10 grid grid-cols-[1fr_auto_1fr] items-center gap-4 px-4 py-4 sm:px-6">
        <Link href="/" aria-label="Explorer home" className="justify-self-start">
          <Image
            src="/explorer-logo.svg"
            alt="Explorer"
            width={867}
            height={187}
            priority
            className="h-9 w-auto"
          />
        </Link>

        <nav aria-label="Products" className="flex items-center gap-2 sm:gap-6">
          {TABS.map(({ label, icon: Icon, current }) => (
            <button
              key={label}
              type="button"
              disabled={!current}
              aria-current={current ? "page" : undefined}
              title={current ? undefined : "Work in progress"}
              className={cn(
                "flex items-center gap-2 border-b-2 px-2 py-3 text-sm font-medium outline-none focus-visible:ring-3 focus-visible:ring-ring/50 sm:px-3",
                current
                  ? "border-foreground text-foreground"
                  : "border-transparent text-muted-foreground disabled:cursor-not-allowed"
              )}
            >
              <Icon aria-hidden className="size-5" />
              <span className="max-sm:sr-only">{label}</span>
            </button>
          ))}
        </nav>

        <button
          type="button"
          disabled
          title="Work in progress"
          className={cn(
            buttonVariants({ variant: "secondary" }),
            "h-10 justify-self-end rounded-full px-4"
          )}
        >
          Sign in
          <ChevronRight aria-hidden />
        </button>
      </header>

      <main className="relative z-10 mx-auto flex w-full max-w-5xl flex-1 flex-col items-center gap-10 px-4 pt-12 sm:px-6 sm:pt-20">
        <h1 className="text-balance text-center text-3xl font-semibold tracking-tight sm:text-5xl">
          Find your next flight, <br className="hidden sm:block" />
          all in one search
        </h1>
        <FlightSearchForm
          value={search}
          onChange={setSearch}
          className="w-full"
        />
      </main>
    </div>
  )
}
