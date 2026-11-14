import userEvent from "@testing-library/user-event"
import { render, screen, within } from "@testing-library/react"
import { describe, expect, test } from "vitest"

import {
  TripOpportunities,
  TripOpportunitiesPlaceholder,
} from "./trip-opportunities"
import { SAMPLE_OPTIONS } from "./trip-opportunities.preview"

describe("TripOpportunities", () => {
  test("lists opportunities as a plain vertical list without flexbox", () => {
    render(<TripOpportunities options={SAMPLE_OPTIONS} />)
    const region = screen.getByRole("region", { name: "Travel opportunities" })
    const list = within(region)
      .getAllByRole("list")
      .find((l) => l.parentElement === region)
    expect(list).toBeDefined()
    expect(list).not.toHaveClass("flex", "flex-wrap")
    expect(list!.children).toHaveLength(SAMPLE_OPTIONS.length)
    for (const li of Array.from(list!.children)) {
      expect(li.tagName).toBe("LI")
      expect(li).not.toHaveClass("flex", "grow")
    }
  })

  test("Book is a split button whose dropdown toggles the travel details", async () => {
    const user = userEvent.setup()
    render(<TripOpportunities options={SAMPLE_OPTIONS.slice(0, 1)} />)
    expect(screen.getByRole("button", { name: "Book" })).toBeEnabled()
    const trigger = screen.getByRole("button", { name: "Travel details" })
    expect(trigger).toHaveAttribute("aria-expanded", "false")
    expect(screen.queryByText("Riga", { selector: "li span" })).toBeNull()

    await user.click(trigger)
    expect(trigger).toHaveAttribute("aria-expanded", "true")
    expect(screen.getAllByText("Riga", { selector: "li span" })[0]).toBeVisible()

    await user.click(trigger)
    expect(trigger).toHaveAttribute("aria-expanded", "false")
  })

  test("shows every visited city on the route without expanding details", () => {
    const multiCity = SAMPLE_OPTIONS.find((o) => o.path.length === 4)!
    render(<TripOpportunities options={[multiCity]} />)
    const stops = screen.getByRole("list", { name: "Cities visited" })
    expect(
      within(stops)
        .getAllByRole("listitem")
        .map((li) => li.textContent)
    ).toEqual(["Amsterdam", "Paris", "Barcelona"])
  })

  test("marks each leg on the route line with its transport type", () => {
    const mixed = SAMPLE_OPTIONS.find((o) => o.path[1]?.transport_type === "TRAINS")!
    const { container } = render(<TripOpportunities options={[mixed]} />)
    const segments = Array.from(
      container.querySelectorAll('ol[aria-label="Cities visited"] > li[title]')
    )
    expect(segments.map((s) => s.getAttribute("title"))).toEqual(
      mixed.path.map((l) => {
        const label = { PLANES: "Plane", TRAINS: "Train", BUSSES: "Bus", FERRIES: "Ferry" }[l.transport_type]
        return `${label}: ${l.from} to ${l.to}`
      })
    )
    for (const s of segments) expect(s.querySelector("svg")).not.toBeNull()
  })

  test("shows departure and return times and the price", () => {
    render(<TripOpportunities options={SAMPLE_OPTIONS.slice(0, 1)} />)
    expect(screen.getByText("07:00")).toBeInTheDocument()
    expect(screen.getByText("23:15")).toBeInTheDocument()
    expect(screen.getByText("Price per adult")).toBeInTheDocument()
    expect(screen.getByText("€89.90")).toBeInTheDocument()
  })

  test("reports an empty result without rendering grid items", () => {
    render(<TripOpportunities options={[]} />)
    expect(
      screen.getByText("No travel opportunities match your search")
    ).toBeInTheDocument()
    expect(screen.queryAllByRole("listitem")).toHaveLength(0)
  })

  test("placeholder uses the same plain list", () => {
    render(<TripOpportunitiesPlaceholder count={4} />)
    const list = screen.getByRole("list")
    expect(list).not.toHaveClass("flex", "flex-wrap")
    expect(list.children).toHaveLength(4)
  })
})

test("distinguishes the single provider-checked price from forecast estimates", () => {
  render(<TripOpportunities options={SAMPLE_OPTIONS.slice(0, 3)}
    priceStatuses={["provider_advertised", "estimated", "adjusted_estimate"]} />)
  expect(screen.getAllByText("Checked with Scrappa/Omio")).toHaveLength(1)
  expect(screen.getByText("Forecast estimate")).toBeInTheDocument()
  expect(screen.getByText("Adjusted forecast estimate")).toBeInTheDocument()
})

test("keeps over-budget cards visible and labels only those options", () => {
  render(<TripOpportunities options={SAMPLE_OPTIONS.slice(0, 2)}
    priceStatuses={["provider_advertised", "estimated"]} overBudgetOptions={[true, false]} />)
  expect(screen.getByText("2 travel opportunities")).toBeInTheDocument()
  expect(screen.getAllByText("Over budget")).toHaveLength(1)
  expect(screen.getByText("Checked with Scrappa/Omio")).toBeInTheDocument()
  expect(screen.getByText("€89.90")).toBeInTheDocument()
})

test("renders estimate-only results without invented times or booking actions", () => {
  const estimates = Array.from({ length: 10 }, (_, index) => ({
    rank: index + 1,
    cities: [{ id: "a", name: "Home" }, { id: "b", name: "Riga" }, { id: "c", name: "Tallinn" }, { id: "a", name: "Home" }],
    departure_date: "2030-01-02", return_date: "2030-01-04",
    total_price: { amount: String(30 + index), currency: "EUR" }, schedule_source: "reference",
  }))
  render(<TripOpportunities options={[]} estimates={estimates} />)
  expect(screen.getByText("10 travel opportunities")).toBeInTheDocument()
  expect(screen.getAllByText("Estimated route · schedule unconfirmed")).toHaveLength(10)
  expect(screen.queryByRole("button", { name: "Book" })).not.toBeInTheDocument()
  expect(screen.queryByText(/\d\d:\d\d/)).not.toBeInTheDocument()
  expect(screen.getAllByText(/Planned dates:/)).toHaveLength(10)
})
