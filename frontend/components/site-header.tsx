import Image from "next/image"
import Link from "next/link"

import { cn } from "@/lib/utils"

const navItem =
  "flex items-center rounded-full px-1 py-2.5 text-[15px] leading-none font-semibold"

/** Placeholder entries: the routes don't exist yet. */
const COMING_SOON = ["About us", "Community"]

export function SiteHeader({ className }: { className?: string }) {
  return (
    <header
      className={cn(
        "flex flex-wrap items-center justify-between gap-x-6 gap-y-3 py-5",
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
          className="h-9 w-auto sm:h-11"
        />
        <p className="mt-1 text-[15px] font-bold text-forest sm:text-base">
          Find your next trip
        </p>
      </Link>
      <nav
        aria-label="Main"
        className="flex flex-wrap items-center gap-x-6 gap-y-2 sm:gap-x-8"
      >
        <Link
          href="/"
          aria-current="page"
          className={cn(navItem, "text-teal hover:text-teal")}
        >
          Explore
        </Link>
        {COMING_SOON.map((label) => (
          <span key={label} className="relative flex items-center justify-center">
            <span
              aria-disabled="true"
              className={cn(navItem, "cursor-default text-foreground/80")}
            >
              {label}
            </span>
            <span className="absolute top-full left-1/2 -translate-x-1/2 text-[11px] leading-none whitespace-nowrap text-muted-foreground">
              Work in progress
            </span>
          </span>
        ))}
        <span
          aria-disabled="true"
          className="flex cursor-default items-center rounded-full bg-mint px-5 py-2.5 text-[15px] leading-none font-semibold"
        >
          My trips
        </span>
      </nav>
    </header>
  )
}
