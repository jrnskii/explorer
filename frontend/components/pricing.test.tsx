import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, test } from "vitest"

import {
  CUSTOM_CREDITS,
  clampCredits,
  customTotalCents,
  formatEuroCents,
  hasCustomDiscount,
} from "@/lib/pricing-data"

import { Pricing } from "./pricing"
import { SiteHeader } from "./site-header"

// Base UI hides the thumb until it has been measured, which never happens in jsdom.
const slider = () => screen.getByRole("slider", { hidden: true })
const total = () => screen.getByTestId("custom-total")

test("Pricing nav item links to /pricing in the same tab", () => {
  render(<SiteHeader current="pricing" />)
  const link = screen.getByRole("link", { name: "Pricing" })
  expect(link).toHaveAttribute("href", "/pricing")
  expect(link).toHaveAttribute("aria-current", "page")
  expect(link).not.toHaveAttribute("target")
})

describe("custom credit pricing logic", () => {
  test.each([
    [1, "€0.50"],
    [10, "€5.00"],
    [19, "€9.50"],
    [20, "€8.00"],
    [25, "€10.00"],
    [50, "€20.00"],
  ])("%i credits cost %s", (credits, expected) => {
    expect(formatEuroCents(customTotalCents(credits))).toBe(expected)
  })

  test("discount starts at exactly 20 credits", () => {
    expect(hasCustomDiscount(19)).toBe(false)
    expect(hasCustomDiscount(20)).toBe(true)
  })

  test("quantities are clamped to 1–50 and whole numbers", () => {
    expect(clampCredits(0)).toBe(1)
    expect(clampCredits(-5)).toBe(1)
    expect(clampCredits(51)).toBe(50)
    expect(clampCredits(12.4)).toBe(12)
    expect(clampCredits(Number.NaN)).toBe(CUSTOM_CREDITS.default)
    expect(customTotalCents(999)).toBe(2000)
  })
})

test("renders heading, subtitle, three plans and the featured card", () => {
  render(<Pricing />)
  expect(
    screen.getByRole("heading", { level: 1, name: "Make room for more adventures." })
  ).toBeInTheDocument()
  expect(
    screen.getByText("Start free or choose how many credits you need.")
  ).toBeInTheDocument()

  const free = screen.getByRole("article", { name: "Free" })
  expect(within(free).getByText("€0")).toBeInTheDocument()
  expect(within(free).getByText("Includes 2 credits every month.")).toBeInTheDocument()
  expect(within(free).getByRole("button", { name: "Get started" })).toBeInTheDocument()
  expect(free).not.toHaveAttribute("data-featured")

  const featured = screen.getByRole("article", { name: "5 credits" })
  expect(featured).toHaveAttribute("data-featured", "true")
  expect(within(featured).getByText("€2.25")).toBeInTheDocument()
  expect(within(featured).getByText("€0.45 per credit.")).toBeInTheDocument()
  expect(within(featured).getByText("MOST POPULAR")).toBeInTheDocument()
  expect(within(featured).getByRole("button", { name: "Buy credits" })).toBeInTheDocument()

  const twelve = screen.getByRole("article", { name: "12 credits" })
  expect(within(twelve).getByText("€4.80")).toBeInTheDocument()
  expect(within(twelve).getByText("€0.40 per credit.")).toBeInTheDocument()
  expect(within(twelve).getByRole("button", { name: "Buy credits" })).toBeInTheDocument()

  expect(screen.getAllByText("MOST POPULAR")).toHaveLength(1)
})

test("package buttons show a checkout/sign-up coming-soon notice without claiming success", async () => {
  const user = userEvent.setup()
  render(<Pricing />)
  expect(screen.queryByRole("status")).not.toBeInTheDocument()

  await user.click(
    within(screen.getByRole("article", { name: "12 credits" })).getByRole("button")
  )
  let panel = screen.getByRole("status")
  expect(panel).toHaveTextContent("Checkout coming soon")
  expect(panel).toHaveTextContent("12 credits · €4.80")
  expect(panel).toHaveTextContent(/No payment has been taken/)

  await user.click(
    within(screen.getByRole("article", { name: "5 credits" })).getByRole("button")
  )
  expect(screen.getByRole("status")).toHaveTextContent("5 credits · €2.25")

  await user.click(screen.getByRole("button", { name: "Get started" }))
  panel = screen.getByRole("status")
  expect(panel).toHaveTextContent("Sign-up coming soon")
  expect(panel).toHaveTextContent(/No account has been created/)

  await user.click(screen.getByRole("button", { name: "Close" }))
  expect(screen.queryByRole("status")).not.toBeInTheDocument()
})

describe("custom credit selector", () => {
  test("defaults to 10 credits / €5.00 with matching purchase button", () => {
    render(<Pricing />)
    expect(
      screen.getByRole("heading", { name: "Or choose your own." })
    ).toBeInTheDocument()
    expect(
      screen.getByText("€0.50 per credit. Get 20% off when you buy 20 or more.")
    ).toBeInTheDocument()
    expect(slider()).toHaveValue("10")
    expect(slider()).toHaveAttribute("aria-label", "Number of credits")
    expect(slider()).toHaveAttribute("min", "1")
    expect(slider()).toHaveAttribute("max", "50")
    expect(screen.getByTestId("custom-quantity")).toHaveTextContent("10 credits")
    expect(total()).toHaveTextContent("€5.00")
    expect(
      screen.getByRole("button", { name: "Buy 10 credits — €5.00" })
    ).toBeInTheDocument()
    expect(screen.queryByText("20% off applied")).not.toBeInTheDocument()
  })

  test("plus and minus keep every readout in sync and stop at 1 and 50", async () => {
    const user = userEvent.setup()
    render(<Pricing />)
    const plus = screen.getByRole("button", { name: "Increase credits" })
    const minus = screen.getByRole("button", { name: "Decrease credits" })

    await user.click(plus)
    expect(slider()).toHaveValue("11")
    expect(total()).toHaveTextContent("€5.50")
    expect(
      screen.getByRole("button", { name: "Buy 11 credits — €5.50" })
    ).toBeInTheDocument()

    for (let i = 0; i < 20; i++) await user.click(minus)
    expect(slider()).toHaveValue("1")
    expect(minus).toBeDisabled()
    expect(total()).toHaveTextContent("€0.50")
    expect(screen.getByRole("button", { name: "Buy 1 credit — €0.50" })).toBeInTheDocument()

    slider().focus()
    await user.keyboard("{End}")
    expect(slider()).toHaveValue("50")
    expect(plus).toBeDisabled()
    expect(total()).toHaveTextContent("€20.00")
    expect(
      screen.getByRole("button", { name: "Buy 50 credits — €20.00" })
    ).toBeInTheDocument()
  })

  test("discount switches on at exactly 20 credits and off again at 19", async () => {
    const user = userEvent.setup()
    render(<Pricing />)
    const plus = screen.getByRole("button", { name: "Increase credits" })
    const minus = screen.getByRole("button", { name: "Decrease credits" })

    for (let i = 0; i < 9; i++) await user.click(plus)
    expect(slider()).toHaveValue("19")
    expect(total()).toHaveTextContent("€9.50")
    expect(screen.queryByText("20% off applied")).not.toBeInTheDocument()

    await user.click(plus)
    expect(slider()).toHaveValue("20")
    expect(total()).toHaveTextContent("€8.00")
    expect(screen.getByText("20% off applied")).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Buy 20 credits — €8.00" })
    ).toBeInTheDocument()

    for (let i = 0; i < 5; i++) await user.click(plus)
    expect(total()).toHaveTextContent("€10.00")

    for (let i = 0; i < 6; i++) await user.click(minus)
    expect(slider()).toHaveValue("19")
    expect(screen.queryByText("20% off applied")).not.toBeInTheDocument()
  })

  test("slider keyboard control updates price and button", async () => {
    const user = userEvent.setup()
    render(<Pricing />)
    slider().focus()
    await user.keyboard("{ArrowRight}")
    expect(slider()).toHaveValue("11")
    await user.keyboard("{Home}")
    expect(total()).toHaveTextContent("€0.50")
    await user.keyboard("{ArrowRight}".repeat(19))
    expect(slider()).toHaveValue("20")
    expect(total()).toHaveTextContent("€8.00")
    expect(screen.getByText("20% off applied")).toBeInTheDocument()
  })

  test("custom purchase button shows the coming-soon notice with the current selection", async () => {
    const user = userEvent.setup()
    render(<Pricing />)
    await user.click(screen.getByRole("button", { name: "Increase credits" }))
    await user.click(screen.getByRole("button", { name: "Buy 11 credits — €5.50" }))
    const panel = screen.getByRole("status")
    expect(panel).toHaveTextContent("Checkout coming soon")
    expect(panel).toHaveTextContent("11 credits · €5.50")
    expect(panel).toHaveTextContent(/No payment has been taken/)
  })
})

test("shows the credit information, keeps contact mailto", () => {
  render(<Pricing />)
  expect(
    screen.getByText(
      "Purchased credits stay available until you use them. Free credits refresh every month."
    )
  ).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "Email Explorer" })).toHaveAttribute(
    "href",
    "mailto:explorer@hack.com"
  )
})

test("pricing FAQ: collapsed by default, one open at a time, toggles closed", async () => {
  const user = userEvent.setup()
  render(<Pricing />)
  const q1 = screen.getByRole("button", { name: "Do purchased credits expire?" })
  const q2 = screen.getByRole("button", { name: "When will Explorer use a credit?" })
  expect(q1).toHaveAttribute("aria-expanded", "false")
  expect(screen.queryByText(/planned not to expire/)).not.toBeInTheDocument()

  await user.click(q1)
  expect(q1).toHaveAttribute("aria-expanded", "true")
  await user.click(q2)
  expect(q1).toHaveAttribute("aria-expanded", "false")
  expect(q2).toHaveAttribute("aria-expanded", "true")
  await user.click(q2)
  expect(q2).toHaveAttribute("aria-expanded", "false")
})
