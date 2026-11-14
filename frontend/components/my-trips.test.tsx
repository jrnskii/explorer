import { act, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, test } from "vitest"

import { MyTrips } from "./my-trips"
import { TripOpportunities } from "./trip-opportunities"
import { SAMPLE_OPTIONS } from "./trip-opportunities.preview"
import {
  SAVED_TRIPS_KEY,
  getSavedTrips,
  removeTrip,
  saveTrip,
  tripId,
} from "@/lib/saved-trips"

beforeEach(() => {
  window.localStorage.clear()
})

describe("saved trips store", () => {
  test("saves a trip once and removes it by id", () => {
    saveTrip(SAMPLE_OPTIONS[0], 2)
    saveTrip(SAMPLE_OPTIONS[0], 2)
    expect(getSavedTrips()).toHaveLength(1)
    expect(getSavedTrips()[0].travelers).toBe(2)
    removeTrip(tripId(SAMPLE_OPTIONS[0]))
    expect(getSavedTrips()).toHaveLength(0)
  })

  test("ignores corrupt or malformed storage", () => {
    window.localStorage.setItem(SAVED_TRIPS_KEY, "{not json")
    expect(getSavedTrips()).toEqual([])
    window.localStorage.setItem(SAVED_TRIPS_KEY, JSON.stringify([{ id: 1 }]))
    expect(getSavedTrips()).toEqual([])
  })
})

describe("MyTrips", () => {
  test("shows an empty state with a link to search", () => {
    render(<MyTrips />)
    expect(screen.getByText("You have no saved trips yet.")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Search trips" })).toHaveAttribute(
      "href",
      "/"
    )
  })

  test("lists every saved trip", () => {
    saveTrip(SAMPLE_OPTIONS[0])
    saveTrip(SAMPLE_OPTIONS[1])
    render(<MyTrips />)
    expect(screen.getByText("2 saved trips, stored in this browser.")).toBeInTheDocument()
    expect(screen.getAllByRole("button", { name: "Travel details" })).toHaveLength(2)
  })

  test("updates when a trip is saved or removed elsewhere", () => {
    render(<MyTrips />)
    act(() => saveTrip(SAMPLE_OPTIONS[0]))
    expect(screen.getByText(/1 saved trip,/)).toBeInTheDocument()
    act(() => removeTrip(tripId(SAMPLE_OPTIONS[0])))
    expect(screen.getByText("You have no saved trips yet.")).toBeInTheDocument()
  })

  test("removing a trip with its bookmark button drops it from the list", async () => {
    const user = userEvent.setup()
    saveTrip(SAMPLE_OPTIONS[0])
    render(<MyTrips />)
    await user.click(screen.getByRole("button", { name: "Remove from My trips" }))
    expect(screen.getByText("You have no saved trips yet.")).toBeInTheDocument()
  })
})

describe("save button on search results", () => {
  test("toggles saved state and persists it", async () => {
    const user = userEvent.setup()
    render(<TripOpportunities options={SAMPLE_OPTIONS.slice(0, 1)} travelers={2} />)
    const save = screen.getByRole("button", { name: "Save to My trips" })
    expect(save).toHaveAttribute("aria-pressed", "false")

    await user.click(save)
    expect(save).toHaveAccessibleName("Remove from My trips")
    expect(save).toHaveAttribute("aria-pressed", "true")
    expect(getSavedTrips()).toHaveLength(1)
    expect(getSavedTrips()[0].travelers).toBe(2)

    await user.click(save)
    expect(save).toHaveAttribute("aria-pressed", "false")
    expect(getSavedTrips()).toHaveLength(0)
  })
})


test("preserves party estimates when saving and reopening a trip", async () => {
  const user = userEvent.setup()
  const option = { ...SAMPLE_OPTIONS[0], total_price: { amount: "20.00", currency: "EUR" } }
  const result = render(<TripOpportunities options={[option]} travelers={2} priceScope="party" />)
  await user.click(screen.getByRole("button", { name: "Save to My trips" }))
  expect(getSavedTrips()[0].priceScope).toBe("party")
  result.unmount()
  render(<MyTrips />)
  expect(screen.getByText("€20")).toBeInTheDocument()
  expect(screen.getByText("estimated total for 2 travellers")).toBeInTheDocument()
  expect(screen.queryByText("€40")).toBeNull()
})
