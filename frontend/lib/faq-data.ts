export const SUPPORT_EMAIL = "explorer@hack.com"

export type FaqCategoryId =
  | "getting-started"
  | "planning"
  | "booking"
  | "membership"
  | "support"

export type FaqItem = {
  id: string
  category: FaqCategoryId
  question: string
  /** Paragraph text; the support email is linkified when rendered. */
  answer: string
  /** Optional bullet list rendered after the answer. */
  bullets?: string[]
  /** Optional paragraph rendered after the bullets. */
  footnote?: string
}

export const FAQ_CATEGORIES: { id: FaqCategoryId; label: string }[] = [
  { id: "getting-started", label: "Getting started" },
  { id: "planning", label: "Planning your trip" },
  { id: "booking", label: "Booking & payments" },
  { id: "membership", label: "Membership & credits" },
  { id: "support", label: "Account & support" },
]

export const FAQ_ITEMS: FaqItem[] = [
  {
    id: "what-is-explorer",
    category: "getting-started",
    question: "What is Explorer?",
    answer:
      "Explorer helps students and budget-conscious travellers discover affordable multi-city round trips. You can explore route ideas, compare transport types and plan a journey back to where you started.",
  },
  {
    id: "how-it-works",
    category: "getting-started",
    question: "How does Explorer work?",
    answer:
      'Choose your departure location, travel date, trip length, number of travellers and maximum transport budget. Select your preferred transport options and click "Find my trip" to discover possible journeys. You can also use Advanced Search to customize your route.',
  },
  {
    id: "multiple-cities",
    category: "getting-started",
    question: "Can I visit more than one city?",
    answer:
      "Yes! Explorer is designed for multi-city travel. You can discover journeys that connect several destinations and include a return to your starting point.",
  },
  {
    id: "choose-cities",
    category: "getting-started",
    question: "Can I choose which cities to visit or avoid?",
    answer:
      "Yes. Advanced Search allows you to specify must-visit cities, avoid certain destinations, choose the number of cities and adjust how much time you want to spend in each location.",
  },
  {
    id: "transport-options",
    category: "planning",
    question: "What transport options can I compare?",
    answer:
      "Explorer is designed to compare flights, trains, buses and ferries. You can select one or multiple transport types to find journeys that match your preferences.",
  },
  {
    id: "budget-includes",
    category: "planning",
    question: "What does my budget include?",
    answer:
      "Your maximum budget applies to the estimated transport costs of your complete journey, including the return route. Accommodation, food, attractions and other personal expenses are not included.",
  },
  {
    id: "flexible-dates",
    category: "planning",
    question: "What if my travel dates are flexible?",
    answer:
      'Select "I\'m flexible with travel dates" to allow Explorer to consider departure dates up to two days before or after your selected date. Your chosen trip length remains unchanged.',
  },
  {
    id: "save-trip",
    category: "planning",
    question: "Can I save a trip and return to it later?",
    answer:
      'Yes. Saved journeys are accessible through "My Trips" in the top toolbar, allowing you to revisit and compare your travel plans.',
  },
  {
    id: "prices-guaranteed",
    category: "planning",
    question: "Are the prices shown guaranteed?",
    answer:
      "No. Transport prices may change depending on availability, demand and the provider. Explorer may display estimated prices, and certain features can help refresh pricing information. Always confirm the final price on the provider's website before booking.",
  },
  {
    id: "book-directly",
    category: "booking",
    question: "Can I book directly through Explorer?",
    answer:
      "Explorer is a travel-planning and comparison platform. When you're ready to book, you'll be redirected to the relevant transport provider's website to complete your purchase.",
  },
  {
    id: "extra-charges",
    category: "booking",
    question: "Does Explorer charge extra for transport bookings?",
    answer:
      "Any applicable Explorer service fees should be clearly disclosed. The final transport price, including any additional provider charges, must be confirmed on the booking website.",
  },
  {
    id: "change-cancel",
    category: "booking",
    question: "What if I need to change or cancel a booking?",
    answer:
      "Changes, cancellations and refunds are handled according to the booking provider's terms and conditions. Contact the provider you booked with for assistance.",
  },
  {
    id: "free-to-use",
    category: "membership",
    question: "Is Explorer free to use?",
    answer:
      "Yes! Explorer offers a Free option with 2 credits per month. Additional features can be unlocked by purchasing credits.",
  },
  {
    id: "credit-cost",
    category: "membership",
    question: "How much do Explorer credits cost?",
    answer: "Explorer offers three credit options:",
    bullets: [
      "Free: 2 credits per month — €0",
      "5 credits — €2.99",
      "12 credits — €6.99",
    ],
    footnote:
      "The paid credit packages are one-time purchases, not recurring subscriptions.",
  },
  {
    id: "credit-use",
    category: "membership",
    question: "What can I use credits for?",
    answer:
      "Credits can unlock additional planning features, such as longer-trip searches and updated journey prices. Explorer should always show the required number of credits before deducting them.",
  },
  {
    id: "credit-expiry",
    category: "membership",
    question: "Do purchased credits expire?",
    answer:
      "Purchased credits are planned not to expire. Free monthly credits may reset according to the applicable allowance rules.",
  },
  {
    id: "account-needed",
    category: "support",
    question: "Do I need an account to use Explorer?",
    answer:
      "You can explore the trip-search experience without signing in. An account may be required to save journeys, purchase credits or access personalized features.",
  },
  {
    id: "contact",
    category: "support",
    question: "How can I contact Explorer?",
    answer: `You can contact the Explorer team by emailing us at ${SUPPORT_EMAIL}. We're happy to help with any questions, feedback or issues you may have.`,
  },
]

/** Items matching the category (or all) and a case-insensitive query over question and answer text. */
export function filterFaq(
  items: FaqItem[],
  category: FaqCategoryId | "all",
  query: string
): FaqItem[] {
  const q = query.trim().toLowerCase()
  return items.filter((item) => {
    if (category !== "all" && item.category !== category) return false
    if (!q) return true
    const haystack = [item.question, item.answer, ...(item.bullets ?? []), item.footnote ?? ""]
      .join(" ")
      .toLowerCase()
    return haystack.includes(q)
  })
}
