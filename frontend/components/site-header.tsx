import Image from "next/image"
import Link from "next/link"
import {
  BadgeDollarSign,
  CircleHelp,
  House,
  LogIn,
  Luggage,
  type LucideIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { RegionPreferences } from "@/components/region-preferences"
import { ThemePicker } from "@/components/theme-picker"
import { cn } from "@/lib/utils"

/** Placeholder entries: the routes don't exist yet. */
const COMING_SOON: { label: string; icon: LucideIcon }[] = [
  { label: "Pricing", icon: BadgeDollarSign },
  { label: "Help", icon: CircleHelp },
  { label: "Log in", icon: LogIn },
]

const navButtonClass =
  "text-foreground hover:bg-hover hover:text-forest"

export function SiteHeader({
  className,
  savedTripsCount = 0,
  current = "home",
}: {
  className?: string
  /** Which page the header is rendered on; marks Home as current only on the homepage. */
  current?: "home" | "help" | "pricing"
  /** Number of trips the user has saved, shown next to "My trips". */
  savedTripsCount?: number
}) {
  return (
    <header
      className={cn(
        "flex flex-wrap items-center justify-between gap-4 py-4",
        className
      )}
    >
      <Link href="/" aria-label="Explorer home">
        <Image
          src="/explorer-logo.svg"
          alt="Explorer"
          width={867}
          height={187}
          priority
          className="h-9 w-auto"
        />
      </Link>
      <nav aria-label="Main" className="flex flex-wrap items-center gap-1">
        <Link
          href="/"
          aria-current={current === "home" ? "page" : undefined}
          className={cn(buttonVariants({ variant: "ghost" }), navButtonClass)}
        >
          <House aria-hidden strokeWidth={1.5} />
          Home
        </Link>
        <RegionPreferences />
        <ThemePicker />
        {COMING_SOON.map(({ label, icon: Icon }) =>
          label === "Help" || label === "Pricing" ? (
            <Link
              key={label}
              href={label === "Help" ? "/help" : "/pricing"}
              aria-current={
                current === label.toLowerCase() ? "page" : undefined
              }
              className={cn(buttonVariants({ variant: "ghost" }), navButtonClass)}
            >
              <Icon aria-hidden strokeWidth={1.5} />
              {label}
            </Link>
          ) : (
          <Button
            key={label}
            variant="ghost"
            disabled
            title="Work in progress"
            className={navButtonClass}
          >
            <Icon aria-hidden strokeWidth={1.5} />
            {label}
          </Button>
          )
        )}
        <Button
          variant="ghost"
          disabled
          title="Work in progress"
          className={navButtonClass}
        >
          <Luggage aria-hidden strokeWidth={1.5} />
          My trips
          <Badge
            aria-label={`${savedTripsCount} saved ${savedTripsCount === 1 ? "trip" : "trips"}`}
            className="bg-badge text-forest"
          >
            {savedTripsCount}
          </Badge>
        </Button>
      </nav>
    </header>
  )
}
