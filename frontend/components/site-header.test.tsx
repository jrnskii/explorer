import { render, screen } from "@testing-library/react"
import { expect, test } from "vitest"

import { SiteHeader } from "./site-header"

test("renders all navigation items", () => {
  render(<SiteHeader />)
  const nav = screen.getByRole("navigation", { name: "Main" })
  for (const name of ["Home", "GBP", "Pricing", "Help", "Log in", "My trips"]) {
    expect(nav).toHaveTextContent(name)
  }
  expect(
    screen.getByRole("button", { name: "Region preferences, currency GBP" })
  ).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("href", "/")
})

test("does not offer a theme color selector", () => {
  render(<SiteHeader />)
  expect(screen.queryByRole("button", { name: /theme color/i })).toBeNull()
})

test("Help links to the FAQ in the same tab", () => {
  render(<SiteHeader />)
  const help = screen.getByRole("link", { name: "Help" })
  expect(help).toHaveAttribute("href", "/help")
  expect(help).not.toHaveAttribute("target")
})

test("each nav item has a decorative icon", () => {
  render(<SiteHeader />)
  const nav = screen.getByRole("navigation", { name: "Main" })
  expect(nav.querySelectorAll('svg[aria-hidden="true"]')).toHaveLength(6)
})

test("shows the saved trips count next to My trips", () => {
  render(<SiteHeader savedTripsCount={3} />)
  expect(screen.getByLabelText("3 saved trips")).toHaveTextContent("3")
})

test("defaults to zero saved trips and singular label for one", () => {
  const { rerender } = render(<SiteHeader />)
  expect(screen.getByLabelText("0 saved trips")).toBeInTheDocument()
  rerender(<SiteHeader savedTripsCount={1} />)
  expect(screen.getByLabelText("1 saved trip")).toBeInTheDocument()
})
