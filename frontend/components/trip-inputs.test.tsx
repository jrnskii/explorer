import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { expect, test, vi } from "vitest"

import { EMPTY_TRIP_INPUTS, TripInputs } from "./trip-inputs"

const disclaimer = "Search multi-city route ideas and compare estimated fares. Unverified routes are labeled as estimates, not bookable availability."

test("sample itinerary help appears on hover and dismisses on Escape", async () => {
  const user = userEvent.setup()
  const onSubmit = vi.fn()
  render(<TripInputs value={EMPTY_TRIP_INPUTS} onChange={vi.fn()} cities={[]} onSubmit={onSubmit} />)
  expect(screen.queryByText(disclaimer)).not.toBeInTheDocument()
  const help = screen.getByRole("button", { name: "About sample itineraries" })
  expect(help).toHaveAttribute("type", "button")
  await user.hover(help)
  expect(await screen.findByText(disclaimer)).toHaveTextContent(disclaimer)
  expect(screen.getAllByText(disclaimer)).toHaveLength(1)
  await user.keyboard("{Escape}")
  await waitFor(() => expect(screen.queryByText(disclaimer)).not.toBeInTheDocument())
  expect(onSubmit).not.toHaveBeenCalled()
})

test("sample itinerary help is available from the keyboard", async () => {
  const user = userEvent.setup()
  render(<TripInputs value={EMPTY_TRIP_INPUTS} onChange={vi.fn()} cities={[]} />)
  screen.getByRole("button", { name: "About sample itineraries" }).focus()
  expect(screen.getByRole("button", { name: "About sample itineraries" })).toHaveFocus()
  expect(await screen.findByText(disclaimer)).toHaveTextContent(disclaimer)
})

test("missing transportation guidance appears on Search hover and keyboard focus without submitting", async () => {
  const user = userEvent.setup()
  const onSubmit = vi.fn()
  const value = {
    ...EMPTY_TRIP_INPUTS,
    departure: { id: "vno", name: "Vilnius", country: "Lithuania" },
    date: new Date(2030, 0, 1),
    budget: "200",
    duration: "3",
    modes: [],
  }
  const { rerender } = render(<TripInputs value={value} onChange={vi.fn()} cities={[]} onSubmit={onSubmit} />)
  const message = "Choose at least one way to travel."
  const search = screen.getByRole("button", { name: "Search" })
  expect(screen.queryByText(message)).not.toBeInTheDocument()
  expect(search).toHaveAttribute("aria-disabled", "true")
  await user.hover(search)
  expect(await screen.findByText(message)).toBeInTheDocument()
  await user.click(search)
  expect(onSubmit).not.toHaveBeenCalled()
  await user.unhover(search)
  await user.keyboard("{Escape}")
  await waitFor(() => expect(screen.queryByText(message)).not.toBeInTheDocument())
  search.focus()
  expect(search).toHaveFocus()
  expect(await screen.findByText(message)).toBeInTheDocument()
  await user.keyboard("{Enter}")
  expect(onSubmit).not.toHaveBeenCalled()
  rerender(<TripInputs value={{ ...value, modes: ["PLANES"] }} onChange={vi.fn()} cities={[]} onSubmit={onSubmit} />)
  await waitFor(() => expect(screen.queryByText(message)).not.toBeInTheDocument())
  await user.click(search)
  expect(onSubmit).toHaveBeenCalledOnce()
})

test("search requires no budget and exposes no budget control", () => {
  render(<TripInputs value={{ ...EMPTY_TRIP_INPUTS, departure: { id: "vno", name: "Vilnius", country: "Lithuania" }, date: new Date(2030, 0, 1), duration: "3" }} cities={[]} onChange={vi.fn()} />)
  expect(screen.queryByRole("combobox", { name: /budget/i })).not.toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Search" })).not.toHaveAttribute("aria-disabled", "true")
})
