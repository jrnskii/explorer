import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { expect, test } from "vitest"

import { Pricing } from "./pricing"
import { SiteHeader } from "./site-header"

test("Pricing nav item links to /pricing in the same tab", () => {
  render(<SiteHeader current="pricing" />)
  const link = screen.getByRole("link", { name: "Pricing" })
  expect(link).toHaveAttribute("href", "/pricing")
  expect(link).toHaveAttribute("aria-current", "page")
  expect(link).not.toHaveAttribute("target")
})

test("renders heading, three plans and the featured card", () => {
  render(<Pricing />)
  expect(
    screen.getByRole("heading", { level: 1, name: "Choose how you explore." })
  ).toBeInTheDocument()
  for (const name of ["Free", "5 credits", "12 credits"]) {
    expect(screen.getByRole("article", { name })).toBeInTheDocument()
  }
  const featured = screen.getByRole("article", { name: "5 credits" })
  expect(featured).toHaveAttribute("data-featured", "true")
  expect(within(featured).getByText("€2.99")).toBeInTheDocument()
  expect(screen.getByText("Most popular")).toBeInTheDocument()
  expect(screen.queryByText(/subscription required/i)).toBeInTheDocument()
})

test("Start exploring returns to the homepage", () => {
  render(<Pricing />)
  expect(screen.getByRole("link", { name: "Start exploring" })).toHaveAttribute(
    "href",
    "/"
  )
})

test("buying shows an inline coming-soon panel that can be closed", async () => {
  const user = userEvent.setup()
  render(<Pricing />)
  expect(screen.queryByRole("status")).not.toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "Get 12 credits" }))
  const panel = screen.getByRole("status")
  expect(panel).toHaveTextContent("12 credits · €6.99")
  expect(panel).toHaveTextContent(/Checkout is coming soon/)
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument()

  await user.click(screen.getByRole("button", { name: "Get 5 credits" }))
  expect(screen.getByRole("status")).toHaveTextContent("5 credits · €2.99")

  await user.click(screen.getByRole("button", { name: "Close" }))
  expect(screen.queryByRole("status")).not.toBeInTheDocument()
})

test("credits explanation and contact mailto", () => {
  render(<Pricing />)
  expect(
    screen.getByRole("heading", { name: "How do credits work?" })
  ).toBeInTheDocument()
  expect(screen.getByText("Start free")).toBeInTheDocument()
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
