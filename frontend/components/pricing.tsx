"use client"

import Link from "next/link"
import { useState } from "react"
import { Check, X } from "lucide-react"

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion"
import { Button, buttonVariants } from "@/components/ui/button"
import {
  CREDIT_STEPS,
  PRICING_FAQ,
  PRICING_PLANS,
  type PricingPlan,
} from "@/lib/pricing-data"
import { SUPPORT_EMAIL } from "@/lib/faq-data"
import { cn } from "@/lib/utils"

function PlanCard({
  plan,
  onSelect,
}: {
  plan: PricingPlan
  onSelect: (plan: PricingPlan) => void
}) {
  const titleId = `plan-${plan.id}-title`
  const ctaClass = cn(
    "h-10 w-full rounded-lg text-sm font-semibold",
    plan.featured
      ? "bg-forest text-white hover:bg-deep"
      : "bg-mint text-deep hover:bg-sage/60"
  )
  return (
    <div className="relative flex pt-3 md:pt-3">
      {plan.featured && (
        <span className="absolute top-0 left-1/2 z-10 -translate-x-1/2 rounded-full bg-forest px-3 py-0.5 text-xs font-semibold whitespace-nowrap text-white">
          Most popular
        </span>
      )}
      <article
        aria-labelledby={titleId}
        data-featured={plan.featured || undefined}
        className={cn(
          "flex w-full flex-col gap-4 rounded-2xl bg-card p-5",
          plan.featured
            ? "border-2 border-forest shadow-[0_4px_16px_rgba(52,92,73,0.10)]"
            : "border border-line"
        )}
      >
        <header className="flex flex-col gap-0.5">
          <h3 id={titleId} className="text-lg font-bold text-ink">
            {plan.name}
          </h3>
          <p className="text-sm text-muted-foreground">{plan.tagline}</p>
        </header>
        <div>
          <p className="text-3xl font-extrabold text-ink">{plan.price}</p>
          <p className="text-sm text-muted-foreground">{plan.allowance}</p>
        </div>
        <ul className="flex flex-1 flex-col gap-2 text-sm text-charcoal">
          {plan.features.map((f) => (
            <li key={f} className="flex items-start gap-2">
              <Check
                aria-hidden
                strokeWidth={2}
                className="mt-0.5 size-4 shrink-0 text-forest"
              />
              {f}
            </li>
          ))}
        </ul>
        {plan.purchasable ? (
          <Button
            type="button"
            variant="ghost"
            className={ctaClass}
            onClick={() => onSelect(plan)}
          >
            {plan.cta}
          </Button>
        ) : (
          <Link
            href="/"
            className={cn(buttonVariants({ variant: "ghost" }), ctaClass)}
          >
            {plan.cta}
          </Link>
        )}
      </article>
    </div>
  )
}

export function Pricing() {
  const [selected, setSelected] = useState<PricingPlan | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)

  return (
    <div className="flex flex-col gap-10">
      <section aria-labelledby="pricing-title" className="flex flex-col gap-4">
        <div className="text-center">
          <h1 id="pricing-title" className="text-3xl font-bold text-ink sm:text-4xl">
            Choose how you explore.
          </h1>
          <p className="mt-2 text-sm text-muted-foreground sm:text-base">
            Start for free. Get extra credits whenever you need them. No
            subscription required.
          </p>
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          {PRICING_PLANS.map((plan) => (
            <PlanCard key={plan.id} plan={plan} onSelect={setSelected} />
          ))}
        </div>

        {selected && (
          <div
            role="status"
            className="flex items-start justify-between gap-3 rounded-xl border border-sage bg-mint-pale p-4 text-sm"
          >
            <div className="flex flex-col gap-1">
              <p className="font-semibold text-ink">
                {selected.name} · {selected.price}
              </p>
              <p className="text-charcoal">
                Checkout is coming soon. These are proposed prices; no payment
                has been taken and no credits have been added to your account.
              </p>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label="Close"
              onClick={() => setSelected(null)}
            >
              <X aria-hidden />
            </Button>
          </div>
        )}

        <p className="text-center text-xs text-muted-foreground">
          Credit packages and policies are proposals for Explorer&apos;s
          upcoming service. Payments are not available in this prototype.
        </p>
      </section>

      <section aria-labelledby="credits-title" className="flex flex-col gap-4">
        <h2 id="credits-title" className="text-center text-2xl font-bold text-ink">
          How do credits work?
        </h2>
        <ol className="grid gap-3 md:grid-cols-3">
          {CREDIT_STEPS.map((step, i) => (
            <li
              key={step.title}
              className="flex items-start gap-3 rounded-xl border border-line bg-card p-4"
            >
              <span
                aria-hidden
                className="flex size-8 shrink-0 items-center justify-center rounded-full bg-mint text-sm font-bold text-deep"
              >
                {i + 1}
              </span>
              <div>
                <h3 className="text-sm font-semibold text-ink">{step.title}</h3>
                <p className="text-sm text-muted-foreground">{step.body}</p>
              </div>
            </li>
          ))}
        </ol>
        <p className="text-center text-sm text-muted-foreground">
          You&apos;ll see how many credits a feature costs before choosing to
          use it.
        </p>
      </section>

      <section aria-labelledby="pricing-faq-title" className="mx-auto flex w-full max-w-3xl flex-col gap-4">
        <h2 id="pricing-faq-title" className="text-center text-2xl font-bold text-ink">
          Pricing questions
        </h2>
        <Accordion
          value={openId ? [openId] : []}
          onValueChange={(v) => setOpenId(v[0] ? String(v[0]) : null)}
          className="overflow-hidden rounded-xl border border-sage bg-card"
        >
          {PRICING_FAQ.map((item) => (
            <AccordionItem key={item.id} value={item.id} className="not-last:border-sage">
              <AccordionTrigger className="text-deep">
                {item.question}
              </AccordionTrigger>
              <AccordionContent className="leading-relaxed text-charcoal">
                <p>{item.answer}</p>
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
      </section>

      <section
        aria-labelledby="pricing-contact-title"
        className="flex flex-col items-start gap-3 rounded-xl border bg-mint p-5 sm:flex-row sm:items-center sm:justify-between"
      >
        <div>
          <h2 id="pricing-contact-title" className="text-base font-bold text-ink">
            Still have questions?
          </h2>
          <p className="text-sm text-charcoal">
            We&apos;re happy to help with credits, pricing and your travel
            plans.
          </p>
        </div>
        <a
          href={`mailto:${SUPPORT_EMAIL}`}
          className={cn(
            buttonVariants({ variant: "default" }),
            "shrink-0 bg-forest text-white hover:bg-deep"
          )}
        >
          Email Explorer
        </a>
      </section>
    </div>
  )
}
