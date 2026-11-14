"use client"

import { Fragment, useMemo, useState } from "react"

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion"
import { buttonVariants } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  FAQ_CATEGORIES,
  FAQ_ITEMS,
  SUPPORT_EMAIL,
  filterFaq,
  type FaqCategoryId,
} from "@/lib/faq-data"
import { cn } from "@/lib/utils"

const MAILTO = `mailto:${SUPPORT_EMAIL}`

const emailLinkClass =
  "font-semibold text-forest underline underline-offset-2 hover:text-deep"

function EmailLink() {
  return (
    <a href={MAILTO} className={emailLinkClass}>
      {SUPPORT_EMAIL}
    </a>
  )
}

/** Renders text, turning any occurrence of the support email into a mailto link. */
function LinkifiedText({ text }: { text: string }) {
  const parts = text.split(SUPPORT_EMAIL)
  return (
    <>
      {parts.map((part, i) => (
        <Fragment key={i}>
          {i > 0 && <EmailLink />}
          {part}
        </Fragment>
      ))}
    </>
  )
}

export function Faq() {
  const [query, setQuery] = useState("")
  const [category, setCategory] = useState<FaqCategoryId | "all">("all")
  const [openId, setOpenId] = useState<string | null>(null)

  const visible = useMemo(
    () => filterFaq(FAQ_ITEMS, category, query),
    [category, query]
  )
  const count = visible.length

  const filters = [{ id: "all" as const, label: "All questions" }, ...FAQ_CATEGORIES]

  return (
    <div className="flex flex-col gap-5">
      <section aria-labelledby="faq-search-title" className="flex flex-col gap-3">
        <h1 id="faq-search-title" className="text-2xl font-bold">
          Find an answer
        </h1>
        <Input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search questions, e.g. credits, budget, bookings..."
          aria-label="Search questions"
          autoComplete="off"
          className="h-11 rounded-xl border-sage bg-card px-4 text-sm md:text-sm"
        />
      </section>

      <div
        role="group"
        aria-label="FAQ categories"
        className="flex flex-wrap gap-2"
      >
        {filters.map((f) => {
          const selected = category === f.id
          return (
            <button
              key={f.id}
              type="button"
              aria-pressed={selected}
              onClick={() => setCategory(f.id)}
              className={cn(
                "rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                selected
                  ? "border-forest bg-forest text-white"
                  : "border-sage bg-mint-pale text-deep hover:bg-mint"
              )}
            >
              {f.label}
            </button>
          )
        })}
      </div>

      <p role="status" aria-live="polite" className="text-sm font-medium text-muted-foreground">
        {count} {count === 1 ? "question" : "questions"}
      </p>

      {count === 0 ? (
        <p className="rounded-xl border border-sage bg-card p-5 text-sm text-charcoal">
          No matching questions found. Try another keyword or contact us at{" "}
          <EmailLink />.
        </p>
      ) : (
        <div className="flex flex-col gap-6">
          {FAQ_CATEGORIES.map((cat) => {
            const items = visible.filter((i) => i.category === cat.id)
            if (items.length === 0) return null
            const openHere = items.find((i) => i.id === openId)?.id
            return (
              <section
                key={cat.id}
                aria-labelledby={`faq-cat-${cat.id}`}
                className="flex flex-col gap-2.5"
              >
                <h2
                  id={`faq-cat-${cat.id}`}
                  className="text-lg font-bold text-forest"
                >
                  {cat.label}
                </h2>
                <Accordion
                  value={openHere ? [openHere] : []}
                  onValueChange={(v) => setOpenId(v[0] ? String(v[0]) : null)}
                  className="overflow-hidden rounded-xl border border-sage bg-card"
                >
                  {items.map((item) => (
                    <AccordionItem key={item.id} value={item.id}>
                      <AccordionTrigger>{item.question}</AccordionTrigger>
                      <AccordionContent className="flex flex-col gap-2 leading-relaxed text-charcoal">
                        <p>
                          <LinkifiedText text={item.answer} />
                        </p>
                        {item.bullets && (
                          <ul className="list-disc space-y-1 pl-5">
                            {item.bullets.map((b) => (
                              <li key={b}>{b}</li>
                            ))}
                          </ul>
                        )}
                        {item.footnote && <p>{item.footnote}</p>}
                      </AccordionContent>
                    </AccordionItem>
                  ))}
                </Accordion>
              </section>
            )
          })}
        </div>
      )}

      <section
        aria-labelledby="faq-contact-title"
        className="mt-2 flex flex-col items-start gap-3 rounded-xl border bg-mint-pale p-5 sm:flex-row sm:items-center sm:justify-between"
      >
        <div>
          <h2 id="faq-contact-title" className="text-base font-bold">
            Still have questions?
          </h2>
          <p className="text-sm text-muted-foreground">
            Can&apos;t find what you&apos;re looking for? We&apos;re here to help.
          </p>
        </div>
        <a
          href={MAILTO}
          className={cn(buttonVariants({ variant: "default" }), "shrink-0")}
        >
          Email Explorer
        </a>
      </section>
    </div>
  )
}
