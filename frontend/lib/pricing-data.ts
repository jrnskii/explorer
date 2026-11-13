export type PricingPlan = {
  id: "free" | "credits-5" | "credits-12"
  name: string
  tagline: string
  /** Display price, e.g. "€2.99". Prototype/proposed only. */
  price: string
  allowance: string
  features: string[]
  cta: string
  featured: boolean
  /** Free plan returns to the homepage; paid plans show the "coming soon" panel. */
  purchasable: boolean
}

export const PRICING_PLANS: PricingPlan[] = [
  {
    id: "free",
    name: "Free",
    tagline: "For your first adventures",
    price: "€0",
    allowance: "2 credits · Every month",
    features: [
      "2 free credits each month",
      "Basic multi-city trip planning",
      "Explore routes within free limits",
      "No payment required",
    ],
    cta: "Start exploring",
    featured: false,
    purchasable: false,
  },
  {
    id: "credits-5",
    name: "5 credits",
    tagline: "For a little more freedom",
    price: "€2.99",
    allowance: "5 credits · One-time purchase",
    features: [
      "5 extra planning credits",
      "Unlock longer-trip searches",
      "Refresh journey prices when available",
      "Purchased credits won't expire",
    ],
    cta: "Get 5 credits",
    featured: true,
    purchasable: true,
  },
  {
    id: "credits-12",
    name: "12 credits",
    tagline: "For your next big adventure",
    price: "€6.99",
    allowance: "12 credits · One-time purchase",
    features: [
      "12 extra planning credits",
      "Plan more journeys",
      "Refresh journey prices when available",
      "Purchased credits won't expire",
    ],
    cta: "Get 12 credits",
    featured: false,
    purchasable: true,
  },
]

export const CREDIT_STEPS = [
  { title: "Start free", body: "Get 2 credits each month to explore Explorer." },
  {
    title: "Unlock more",
    body: "Use credits for longer-trip searches and supported price refreshes.",
  },
  {
    title: "Pay your way",
    body: "Buy extra credits when you need them, without a subscription.",
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
