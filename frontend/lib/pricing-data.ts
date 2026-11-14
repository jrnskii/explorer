export type PricingPlan = {
  id: "free" | "credits-5" | "credits-12"
  name: string
  /** Number of credits included (monthly for the free plan, one-time otherwise). */
  credits: number
  /** Price in euro cents; 0 for the free plan. */
  priceCents: number
  /** Whether credits are granted monthly or bought once. */
  billing: "monthly" | "one-time"
  /** Display price, e.g. "€2.25". Prototype/proposed only. */
  price: string
  /** Short line under the price. */
  note: string
  cta: string
  featured: boolean
}

export const CUSTOM_CREDITS = {
  min: 1,
  max: 50,
  default: 10,
  step: 1,
  /** Quantity from which the discount applies (inclusive). */
  discountFrom: 20,
  discountPercent: 20,
  /** Price per credit in euro cents. */
  unitCents: 50,
} as const

/** Clamps to a whole number within the allowed range; non-finite input falls back to the default. */
export function clampCredits(value: number): number {
  if (!Number.isFinite(value)) return CUSTOM_CREDITS.default
  return Math.min(
    CUSTOM_CREDITS.max,
    Math.max(CUSTOM_CREDITS.min, Math.round(value))
  )
}

export function hasCustomDiscount(quantity: number): boolean {
  return clampCredits(quantity) >= CUSTOM_CREDITS.discountFrom
}

/** Per-credit price in cents for a custom purchase (€0.50, or €0.40 from 20 credits). */
export function customUnitCents(quantity: number): number {
  return hasCustomDiscount(quantity)
    ? (CUSTOM_CREDITS.unitCents * (100 - CUSTOM_CREDITS.discountPercent)) / 100
    : CUSTOM_CREDITS.unitCents
}

/** Total in euro cents; integer arithmetic avoids floating-point rounding errors. */
export function customTotalCents(quantity: number): number {
  const q = clampCredits(quantity)
  return q * customUnitCents(q)
}

export function formatEuroCents(cents: number): string {
  return `€${(cents / 100).toFixed(2)}`
}

/** Whole-number percentage saved per credit versus the standard €0.50 rate; 0 when there is no saving. */
export function planSavingsPercent(plan: PricingPlan): number {
  if (plan.priceCents <= 0 || plan.credits <= 0) return 0
  const perCredit = plan.priceCents / plan.credits
  return Math.max(
    0,
    Math.round(100 - (perCredit / CUSTOM_CREDITS.unitCents) * 100)
  )
}

/** Credits still needed to reach the bulk discount; 0 once reached. */
export function creditsUntilDiscount(quantity: number): number {
  return Math.max(0, CUSTOM_CREDITS.discountFrom - clampCredits(quantity))
}

export const PRICING_PLANS: PricingPlan[] = [
  {
    id: "free",
    name: "Free",
    credits: 2,
    priceCents: 0,
    billing: "monthly",
    price: "€0",
    note: "Includes 2 credits every month.",
    cta: "Get started",
    featured: false,
  },
  {
    id: "credits-5",
    name: "5 credits",
    credits: 5,
    priceCents: 225,
    billing: "one-time",
    price: "€2.25",
    note: "€0.45 per credit.",
    cta: "Buy credits",
    featured: true,
  },
  {
    id: "credits-12",
    name: "12 credits",
    credits: 12,
    priceCents: 480,
    billing: "one-time",
    price: "€4.80",
    note: "€0.40 per credit.",
    cta: "Buy credits",
    featured: false,
  },
]

export const PRICING_FAQ = [
  {
    id: "expire",
    question: "Do purchased credits expire?",
    answer:
      "Purchased credits are planned not to expire. Free monthly credits may reset when a new month begins. Final terms will be available before purchases launch.",
  },
  {
    id: "when-used",
    question: "When will Explorer use a credit?",
    answer:
      "Explorer will show the credit cost before you confirm a credit-based action, such as a longer-trip search. Basic trip planning within the free limits does not require a paid package.",
  },
  {
    id: "no-journey",
    question: "What happens if a search doesn't find a journey?",
    answer:
      "Live trip-search and credit-refund rules are not implemented yet. We will explain exactly when credits are charged and whether unsuccessful searches are refunded before paid features launch.",
  },
  {
    id: "buy-now",
    question: "Can I buy credits now?",
    answer:
      "Not yet. This is a working prototype. The prices are proposed, and secure payments, real accounts and purchased credit balances have not been connected.",
  },
]
