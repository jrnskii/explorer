import type { Metadata } from "next"

import { PageBackdrop } from "@/components/page-backdrop"
import { Pricing } from "@/components/pricing"
import { SiteFooter } from "@/components/site-footer"
import { SiteHeader } from "@/components/site-header"

export const metadata: Metadata = {
  title: "Pricing — Explorer",
  description:
    "Proposed credit packages for Explorer. Start free; no subscription required.",
}

export default function PricingPage() {
  return (
    <>
      <PageBackdrop />
      <div className="relative z-10 mx-auto w-full max-w-5xl px-4 sm:px-6">
        <SiteHeader current="pricing" />
        <main className="py-6">
          <Pricing />
        </main>
      </div>
      <SiteFooter className="relative z-10" />
    </>
  )
}
