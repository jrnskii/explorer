import type { Metadata } from "next"
import { connection } from "next/server"
import { Suspense } from "react"

import { Faq } from "@/components/faq"
import { SiteFooter } from "@/components/site-footer"
import { SiteHeader } from "@/components/site-header"
import { Skeleton } from "@/components/ui/skeleton"

export const metadata: Metadata = {
  title: "Help & FAQ — Explorer",
  description: "Answers to common questions about planning trips with Explorer.",
}

/** Rendered on the server for every request (not prerendered at build time). */
async function ServerRenderedFaq() {
  await connection()
  return <Faq />
}

function FaqFallback() {
  return (
    <div className="flex flex-col gap-5" aria-busy="true">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-11 w-full rounded-xl" />
      <Skeleton className="h-8 w-full" />
      <Skeleton className="h-64 w-full rounded-xl" />
    </div>
  )
}

export default function HelpPage() {
  return (
    <>
      <div className="mx-auto w-full max-w-5xl px-4 sm:px-6">
        <SiteHeader current="help" />
        <main className="py-6">
          <div className="mx-auto w-full max-w-3xl">
            <Suspense fallback={<FaqFallback />}>
              <ServerRenderedFaq />
            </Suspense>
          </div>
        </main>
      </div>
      <SiteFooter />
    </>
  )
}
