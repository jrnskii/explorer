import Image from "next/image"
import Link from "next/link"
import {
  CircleHelp,
  House,
  type LucideIcon,
} from "lucide-react"

import { MyTripsLink } from "@/components/my-trips-link"
import { buttonVariants } from "@/components/ui/button"
import { RegionPreferences } from "@/components/region-preferences"

import { cn } from "@/lib/utils"

const NAV_LINKS: { label: string; href: string; icon: LucideIcon }[] = [
  { label: "Help", href: "/help", icon: CircleHelp },
]

const navButtonClass =
  "text-foreground hover:bg-hover hover:text-forest"

export function SiteHeader({
  className,
  current = "home",
}: {
  className?: string
  /** Which page the header is rendered on; marks Home as current only on the homepage. */
  current?: "home" | "help" | "pricing" | "login" | "my-trips"
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
        <RegionPreferences autoDetect />

        {NAV_LINKS.map(({ label, href, icon: Icon }) => (
          <Link
            key={label}
            href={href}
            aria-current={
              current === href.slice(1) ? "page" : undefined
            }
            className={cn(buttonVariants({ variant: "ghost" }), navButtonClass)}
          >
            <Icon aria-hidden strokeWidth={1.5} />
            {label}
          </Link>
        ))}
        <MyTripsLink
          current={current === "my-trips"}
          className={navButtonClass}
        />
      </nav>
    </header>
  )
}
