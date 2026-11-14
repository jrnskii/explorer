import { act, render, screen } from "@testing-library/react"
import { beforeEach, expect, test } from "vitest"

import { SiteHeader } from "./site-header"
import { SAMPLE_OPTIONS } from "./trip-opportunities.preview"
import { saveTrip } from "@/lib/saved-trips"

beforeEach(() => window.localStorage.clear())

test("renders all navigation items", () => {
  render(<SiteHeader />)
  expect(screen.queryByRole("link", { name: "Pricing" })).not.toBeInTheDocument()
  expect(screen.queryByRole("link", { name: "Log in" })).not.toBeInTheDocument()
  const nav = screen.getByRole("navigation", { name: "Main" })
  for (const name of ["Home", "GBP", "Help", "My trips"]) {
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
  expect(nav.querySelectorAll('svg[aria-hidden="true"]')).toHaveLength(4)
})

test("My trips links to /my-trips in the same tab", () => {
  render(<SiteHeader current="my-trips" />)
  const link = screen.getByRole("link", { name: /My trips/ })
  expect(link).toHaveAttribute("href", "/my-trips")
  expect(link).toHaveAttribute("aria-current", "page")
  expect(link).not.toHaveAttribute("target")
})

test("shows the saved trips count next to My trips", () => {
  saveTrip(SAMPLE_OPTIONS[0])
  saveTrip(SAMPLE_OPTIONS[1])
  render(<SiteHeader />)
  expect(screen.getByLabelText("2 saved trips")).toHaveTextContent("2")
})

test("defaults to zero saved trips and singular label for one", () => {
  render(<SiteHeader />)
  expect(screen.getByLabelText("0 saved trips")).toBeInTheDocument()
  act(() => saveTrip(SAMPLE_OPTIONS[0]))
  expect(screen.getByLabelText("1 saved trip")).toBeInTheDocument()
})
