import Image from "next/image"
import Link from "next/link"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

/** Placeholder entries: the routes don't exist yet. */
const COMING_SOON = ["About us", "Community"]

export function SiteHeader({ className }: { className?: string }) {
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
      <nav aria-label="Main" className="flex flex-wrap items-center gap-2">
        <Button
          variant="secondary"
          nativeButton={false}
          render={<Link href="/" aria-current="page" />}
        >
          Explore
        </Button>
        {COMING_SOON.map((label) => (
          <Button key={label} variant="ghost" disabled title="Work in progress">
            {label}
          </Button>
        ))}
        <Button variant="outline" disabled title="Work in progress">
          My trips
        </Button>
      </nav>
    </header>
  )
}
