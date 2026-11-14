import type { Metadata } from "next"

import { MyTrips } from "@/components/my-trips"
import { PageBackdrop } from "@/components/page-backdrop"
import { SiteFooter } from "@/components/site-footer"
import { SiteHeader } from "@/components/site-header"

export const metadata: Metadata = {
  title: "My trips — Explorer",
  description: "Trips you have saved on Explorer.",
}

export default function MyTripsPage() {
  return (
    <>
      <PageBackdrop />
      <div className="relative z-10 mx-auto w-full max-w-5xl px-4 sm:px-6">
        <SiteHeader current="my-trips" />
        <main className="py-6">
          <MyTrips />
        </main>
      </div>
      <SiteFooter className="relative z-10" />
    </>
  )
}
