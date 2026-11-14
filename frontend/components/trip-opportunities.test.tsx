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
