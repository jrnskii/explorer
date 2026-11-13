"use client"

import { useState } from "react"
import { Minus, Plus, X } from "lucide-react"

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion"
import { Button } from "@/components/ui/button"
import { Slider } from "@/components/ui/slider"
import {
  CUSTOM_CREDITS,
  PRICING_FAQ,
  PRICING_PLANS,
  clampCredits,
  customTotalCents,
  customUnitCents,
  formatEuroCents,
  hasCustomDiscount,
  type PricingPlan,
} from "@/lib/pricing-data"
import { SUPPORT_EMAIL } from "@/lib/faq-data"
import { cn } from "@/lib/utils"

/*
 * The Pricing page uses its own fixed palette so it is unaffected by the
 * app-wide theme picker: rosso #69070E, ink #171717, white, soft #FAF9F8,
 * muted #666666 and border #E9E7E6. Poppins comes from the root layout.
 */
const solidButton =
  "h-10 rounded-md bg-[#69070E] px-4 text-sm font-semibold text-white hover:bg-[#4F050B]"
const stepperButton =
  "size-10 shrink-0 rounded-md border-[#E9E7E6] bg-white text-[#171717] hover:bg-[#FAF9F8] hover:text-[#171717] dark:border-[#E9E7E6] dark:bg-white dark:hover:bg-[#FAF9F8]"

type Notice = {
  source: "plans" | "custom"
  title: string
  message: string
}

const NO_PAYMENT =
  "No payment has been taken and no credits have been added to your account."

function PlanCard({
  plan,
  onSelect,
}: {
  plan: PricingPlan
  onSelect: (plan: PricingPlan) => void
}) {
  const titleId = `plan-${plan.id}-title`
  return (
    <article
      aria-labelledby={titleId}
      data-featured={plan.featured || undefined}
      className={cn(
        "flex flex-col rounded-md border p-6",
        plan.featured
          ? "border-[#69070E] bg-[#69070E] text-white"
          : "border-[#E9E7E6] bg-[#FAF9F8] text-[#171717]"
      )}
    >
      <p
        aria-hidden={plan.featured ? undefined : true}
        className="h-4 text-[11px] leading-4 font-medium tracking-wider text-white/80"
      >
        {plan.featured ? "MOST POPULAR" : ""}
      </p>
      <h2
        id={titleId}
        className={cn(
          "mt-2 text-base font-medium",
          plan.featured ? "text-white" : "text-[#171717]"
        )}
      >
        {plan.name}
      </h2>
      <p className="mt-3 text-4xl font-semibold">{plan.price}</p>
      <p
        className={cn(
          "mt-2 text-sm",
          plan.featured ? "text-white/80" : "text-[#666666]"
        )}
      >
        {plan.note}
      </p>
      <div className="mt-auto pt-8">
        <Button
          type="button"
          className={cn(
            solidButton,
            "w-full",
            plan.featured &&
              "border-white bg-white text-[#69070E] hover:bg-[#FAF9F8]"
          )}
          onClick={() => onSelect(plan)}
        >
          {plan.cta}
        </Button>
      </div>
    </article>
  )
}

function NoticePanel({
  notice,
  onClose,
}: {
  notice: Notice
  onClose: () => void
}) {
  return (
    <div
      role="status"
      className="flex items-start justify-between gap-3 rounded-md border border-[#E9E7E6] bg-[#FAF9F8] p-4 text-sm"
    >
      <div className="flex flex-col gap-1">
        <p className="font-semibold text-[#171717]">{notice.title}</p>
        <p className="text-[#666666]">{notice.message}</p>
      </div>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label="Close"
        className="text-[#171717] hover:bg-[#E9E7E6] hover:text-[#171717]"
        onClick={onClose}
      >
        <X aria-hidden />
      </Button>
    </div>
  )
}

export function Pricing() {
  const [notice, setNotice] = useState<Notice | null>(null)
  const [quantity, setQuantity] = useState<number>(CUSTOM_CREDITS.default)
  const [openId, setOpenId] = useState<string | null>(null)

  const totalCents = customTotalCents(quantity)
  const total = formatEuroCents(totalCents)
  const discounted = hasCustomDiscount(quantity)
  const creditsLabel = `${quantity} ${quantity === 1 ? "credit" : "credits"}`

  const selectPlan = (plan: PricingPlan) =>
    setNotice(
      plan.id === "free"
        ? {
            source: "plans",
            title: "Sign-up coming soon",
            message:
              "Accounts are not available yet, so you can't get started with the Free plan at the moment. No account has been created.",
          }
        : {
            source: "plans",
            title: "Checkout coming soon",
            message: `${plan.name} · ${plan.price}. ${NO_PAYMENT}`,
          }
    )

  return (
    <div className="flex w-full flex-col gap-10 rounded-md border border-[#E9E7E6] bg-white px-4 py-10 font-sans text-[#171717] sm:px-8 sm:py-12">
      <section
        aria-labelledby="pricing-title"
        className="mx-auto flex w-full max-w-4xl flex-col gap-8"
      >
        <div className="text-center">
          <h1
            id="pricing-title"
            className="text-3xl font-semibold text-[#171717] sm:text-4xl"
          >
            Make room for more adventures.
          </h1>
          <p className="mt-3 text-base text-[#666666]">
            Start free or choose how many credits you need.
          </p>
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          {PRICING_PLANS.map((plan) => (
            <PlanCard key={plan.id} plan={plan} onSelect={selectPlan} />
          ))}
        </div>

        {notice?.source === "plans" && (
          <NoticePanel notice={notice} onClose={() => setNotice(null)} />
        )}
      </section>

      <section
        aria-labelledby="custom-title"
        className="mx-auto flex w-full max-w-4xl flex-col gap-5 rounded-md border border-[#E9E7E6] p-6 sm:p-8"
      >
        <div>
          <h2 id="custom-title" className="text-xl font-semibold text-[#171717]">
            Or choose your own.
          </h2>
          <p className="mt-1 text-sm text-[#666666]">
            €0.50 per credit. Get 20% off when you buy 20 or more.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label="Decrease credits"
            className={stepperButton}
            disabled={quantity <= CUSTOM_CREDITS.min}
            onClick={() => setQuantity((q) => clampCredits(q - CUSTOM_CREDITS.step))}
          >
            <Minus aria-hidden />
          </Button>
          <Slider
            min={CUSTOM_CREDITS.min}
            max={CUSTOM_CREDITS.max}
            step={CUSTOM_CREDITS.step}
            value={[quantity]}
            onValueChange={(v) => {
              const next = Array.isArray(v) ? v[0] : v
              setQuantity(clampCredits(Number(next)))
            }}
            thumbProps={{
              getAriaLabel: () => "Number of credits",
              getAriaValueText: (_formatted, value) =>
                `${value} ${value === 1 ? "credit" : "credits"}`,
            }}
            className={cn(
              "px-2",
              "[&_[data-slot=slider-track]]:h-1.5 [&_[data-slot=slider-track]]:bg-[#E9E7E6]",
              "[&_[data-slot=slider-range]]:bg-[#69070E]",
              "[&_[data-slot=slider-thumb]]:size-5 [&_[data-slot=slider-thumb]]:border-[#69070E] [&_[data-slot=slider-thumb]]:ring-[#69070E]/30"
            )}
          />
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label="Increase credits"
            className={stepperButton}
            disabled={quantity >= CUSTOM_CREDITS.max}
            onClick={() => setQuantity((q) => clampCredits(q + CUSTOM_CREDITS.step))}
          >
            <Plus aria-hidden />
          </Button>
        </div>

        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p
              data-testid="custom-quantity"
              className="text-sm font-medium text-[#171717]"
            >
              {creditsLabel}
            </p>
            <p
              data-testid="custom-total"
              className="text-3xl font-semibold text-[#171717]"
            >
              {total}
            </p>
            <p className="text-sm text-[#666666]">
              {formatEuroCents(customUnitCents(quantity))} per credit
            </p>
            <p className="min-h-5 text-sm font-medium text-[#69070E]">
              {discounted ? `${CUSTOM_CREDITS.discountPercent}% off applied` : ""}
            </p>
          </div>
          <Button
            type="button"
            className={cn(solidButton, "w-full sm:w-auto")}
            onClick={() =>
              setNotice({
                source: "custom",
                title: "Checkout coming soon",
                message: `${creditsLabel} · ${total}. ${NO_PAYMENT}`,
              })
            }
          >
            Buy {creditsLabel} — {total}
          </Button>
        </div>

        {notice?.source === "custom" && (
          <NoticePanel notice={notice} onClose={() => setNotice(null)} />
        )}
      </section>

      <div className="mx-auto flex w-full max-w-4xl flex-col gap-2 text-sm text-[#666666]">
        <p>
          Purchased credits stay available until you use them. Free credits
          refresh every month.
        </p>
        <p className="text-xs">
          Credit packages and policies are proposals for Explorer&apos;s
          upcoming service. Payments are not available in this prototype.
        </p>
      </div>

      <section
        aria-labelledby="pricing-faq-title"
        className="mx-auto flex w-full max-w-4xl flex-col gap-3"
      >
        <h2
          id="pricing-faq-title"
          className="text-xl font-semibold text-[#171717]"
        >
          Pricing questions
        </h2>
        <Accordion
          value={openId ? [openId] : []}
          onValueChange={(v) => setOpenId(v[0] ? String(v[0]) : null)}
          className="border-t border-[#E9E7E6]"
        >
          {PRICING_FAQ.map((item) => (
            <AccordionItem
              key={item.id}
              value={item.id}
              className="border-b border-[#E9E7E6]"
            >
              <AccordionTrigger className="px-0 text-[#171717] hover:bg-transparent sm:px-0 [&_svg]:text-[#69070E]">
                {item.question}
              </AccordionTrigger>
              <AccordionContent className="px-0 leading-relaxed text-[#666666] sm:px-0">
                <p>{item.answer}</p>
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
        <p className="text-sm text-[#666666]">
          Still have questions?{" "}
          <a
            href={`mailto:${SUPPORT_EMAIL}`}
            className="font-medium text-[#69070E] underline underline-offset-4"
          >
            Email Explorer
          </a>
        </p>
      </section>
    </div>
  )
}
