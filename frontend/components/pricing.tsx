"use client"

import { useState } from "react"
import { Info, Minus, Plus, X } from "lucide-react"

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Slider } from "@/components/ui/slider"
import {
  CUSTOM_CREDITS,
  PRICING_FAQ,
  PRICING_PLANS,
  clampCredits,
  creditsUntilDiscount,
  customTotalCents,
  customUnitCents,
  formatEuroCents,
  hasCustomDiscount,
  planSavingsPercent,
  type PricingPlan,
} from "@/lib/pricing-data"
import { SUPPORT_EMAIL } from "@/lib/faq-data"
import { cn } from "@/lib/utils"

const solidButton =
  "h-10 rounded-full bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-deep"
const stepperButton =
  "size-10 shrink-0 rounded-full border-sage bg-card text-foreground hover:bg-hover hover:text-forest dark:bg-card dark:hover:bg-muted"

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
  const savings = planSavingsPercent(plan)
  return (
    <article
      aria-labelledby={titleId}
      data-featured={plan.featured || undefined}
      className={cn(
        "flex flex-col rounded-xl border p-6",
        plan.featured
          ? "border-forest bg-forest text-white"
          : "border-sage bg-card text-card-foreground"
      )}
    >
      <p
        aria-hidden={plan.featured ? undefined : true}
        className="h-4 text-[11px] leading-4 font-medium tracking-wider text-white/80"
      >
        {plan.featured ? "MOST POPULAR" : ""}
      </p>
      <div className="mt-2 flex items-center justify-between gap-2">
        <h2
          id={titleId}
          className={cn(
            "text-base font-medium",
            plan.featured ? "text-white" : "text-foreground"
          )}
        >
          {plan.name}
        </h2>
        {savings > 0 && (
          <Badge
            className={
              plan.featured ? "bg-white text-forest" : "bg-badge text-forest"
            }
          >
            Save {savings}%
          </Badge>
        )}
      </div>
      <div className="mt-3 flex items-baseline gap-2">
        <p className="text-4xl font-semibold">{plan.price}</p>
        <span
          className={cn(
            "text-sm",
            plan.featured ? "text-white/80" : "text-muted-foreground"
          )}
        >
          {plan.billing === "monthly" ? "per month" : "one-time"}
        </span>
      </div>
      <p
        className={cn(
          "mt-2 text-sm",
          plan.featured ? "text-white/80" : "text-muted-foreground"
        )}
      >
        {plan.note}
      </p>
      <div className="mt-auto pt-6">
        <Button
          type="button"
          className={cn(
            solidButton,
            "w-full",
            plan.featured &&
              "border-white bg-white text-forest hover:bg-hover"
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
      className="flex items-start justify-between gap-3 rounded-xl border border-sage bg-card p-4 text-sm"
    >
      <div className="flex flex-col gap-1">
        <p className="font-semibold text-foreground">{notice.title}</p>
        <p className="text-muted-foreground">{notice.message}</p>
      </div>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label="Close"
        className="text-foreground hover:bg-hover hover:text-forest"
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
  const untilDiscount = creditsUntilDiscount(quantity)
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
    <div className="flex w-full flex-col gap-10 rounded-xl border border-sage bg-background/85 px-4 py-10 font-sans text-foreground backdrop-blur-md sm:px-8 sm:py-12">
      <section
        aria-labelledby="pricing-title"
        className="mx-auto flex w-full max-w-4xl flex-col gap-8"
      >
        <div className="text-center">
          <h1
            id="pricing-title"
            className="text-3xl font-semibold text-foreground sm:text-4xl"
          >
            Make room for more adventures.
          </h1>
          <p className="mt-3 text-base text-muted-foreground">
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
        className="mx-auto grid w-full max-w-4xl gap-6 rounded-xl border border-sage bg-card/80 p-6 sm:p-8 md:grid-cols-[1fr_16rem]"
      >
        <div className="flex flex-col gap-5">
          <div>
            <h2
              id="custom-title"
              className="text-xl font-semibold text-foreground"
            >
              Or choose your own.
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
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
              onClick={() =>
                setQuantity((q) => clampCredits(q - CUSTOM_CREDITS.step))
              }
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
                "[&_[data-slot=slider-track]]:h-1.5 [&_[data-slot=slider-track]]:bg-sage",
                "[&_[data-slot=slider-range]]:bg-forest",
                "[&_[data-slot=slider-thumb]]:size-5 [&_[data-slot=slider-thumb]]:border-forest [&_[data-slot=slider-thumb]]:ring-forest/30"
              )}
            />
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label="Increase credits"
              className={stepperButton}
              disabled={quantity >= CUSTOM_CREDITS.max}
              onClick={() =>
                setQuantity((q) => clampCredits(q + CUSTOM_CREDITS.step))
              }
            >
              <Plus aria-hidden />
            </Button>
          </div>

          <div
            className="flex justify-between text-xs text-muted-foreground"
            aria-hidden
          >
            <span>{CUSTOM_CREDITS.min}</span>
            <span>{CUSTOM_CREDITS.discountFrom}+ credits: 20% off</span>
            <span>{CUSTOM_CREDITS.max}</span>
          </div>

          <p
            data-testid="custom-discount-hint"
            className="min-h-5 text-sm font-medium text-forest"
          >
            {discounted
              ? `${CUSTOM_CREDITS.discountPercent}% off applied`
              : `Add ${untilDiscount} more ${untilDiscount === 1 ? "credit" : "credits"} to save ${CUSTOM_CREDITS.discountPercent}%`}
          </p>
        </div>

        <div className="flex flex-col gap-4 rounded-xl border border-sage bg-card p-5">
          <dl className="flex flex-col gap-3 text-sm">
            <div className="flex items-baseline justify-between gap-2">
              <dt className="text-muted-foreground">Credits</dt>
              <dd
                data-testid="custom-quantity"
                className="font-medium text-foreground"
              >
                {creditsLabel}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-2">
              <dt className="text-muted-foreground">Rate</dt>
              <dd className="font-medium text-foreground">
                {formatEuroCents(customUnitCents(quantity))} per credit
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-2 border-t border-sage pt-3">
              <dt className="font-medium text-foreground">Total</dt>
              <dd
                data-testid="custom-total"
                className="text-3xl font-semibold text-foreground"
              >
                {total}
              </dd>
            </div>
          </dl>
          <Button
            type="button"
            className={cn(solidButton, "w-full")}
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
          <div className="md:col-span-2">
            <NoticePanel notice={notice} onClose={() => setNotice(null)} />
          </div>
        )}
      </section>

      <div className="mx-auto flex w-full max-w-4xl flex-col gap-2 text-sm text-muted-foreground">
        <p>
          Purchased credits stay available until you use them. Free credits
          refresh every month.
        </p>
        <p className="flex items-start gap-2 rounded-xl border border-sage bg-card/80 p-3 text-xs">
          <Info aria-hidden className="mt-0.5 size-4 shrink-0 text-forest" />
          <span>
            Credit packages and policies are proposals for Explorer&apos;s
            upcoming service. Payments are not available in this prototype.
          </span>
        </p>
      </div>

      <section
        aria-labelledby="pricing-faq-title"
        className="mx-auto flex w-full max-w-4xl flex-col gap-3"
      >
        <h2
          id="pricing-faq-title"
          className="text-xl font-semibold text-foreground"
        >
          Pricing questions
        </h2>
        <Accordion
          value={openId ? [openId] : []}
          onValueChange={(v) => setOpenId(v[0] ? String(v[0]) : null)}
          className="border-t border-sage"
        >
          {PRICING_FAQ.map((item) => (
            <AccordionItem
              key={item.id}
              value={item.id}
              className="border-b border-sage"
            >
              <AccordionTrigger className="px-0 text-foreground hover:bg-transparent sm:px-0 [&_svg]:text-forest">
                {item.question}
              </AccordionTrigger>
              <AccordionContent className="px-0 leading-relaxed text-muted-foreground sm:px-0">
                <p>{item.answer}</p>
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
        <p className="text-sm text-muted-foreground">
          Still have questions?{" "}
          <a
            href={`mailto:${SUPPORT_EMAIL}`}
            className="font-medium text-forest underline underline-offset-4"
          >
            Email Explorer
          </a>
        </p>
      </section>
    </div>
  )
}
