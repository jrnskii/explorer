import * as React from "react"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { expect, test, vi } from "vitest"

import { EMPTY_TRIP_INPUTS, TripInputs, type TripInputsValue } from "./trip-inputs"

const disclaimer = "Published transport schedules with forecast prices. Final fares and availability require provider confirmation."

test("trip estimate help appears on hover and dismisses on Escape", async () => {
  const user = userEvent.setup()
  const onSubmit = vi.fn()
  render(<TripInputs value={EMPTY_TRIP_INPUTS} onChange={vi.fn()} cities={[]} onSubmit={onSubmit} />)
  expect(screen.queryByText(disclaimer)).not.toBeInTheDocument()
  const help = screen.getByRole("button", { name: "About trip estimates" })
  expect(help).toHaveAttribute("type", "button")
  await user.hover(help)
  expect(await screen.findByText(disclaimer)).toHaveTextContent(disclaimer)
  expect(screen.getAllByText(disclaimer)).toHaveLength(1)
  await user.keyboard("{Escape}")
  await waitFor(() => expect(screen.queryByText(disclaimer)).not.toBeInTheDocument())
  expect(onSubmit).not.toHaveBeenCalled()
})

test("trip estimate help is available from the keyboard", async () => {
  const user = userEvent.setup()
  render(<TripInputs value={EMPTY_TRIP_INPUTS} onChange={vi.fn()} cities={[]} />)
  screen.getByRole("button", { name: "About trip estimates" }).focus()
  await user.keyboard("{Shift>}{Tab}{/Shift}{Tab}")
  expect(screen.getByRole("button", { name: "About trip estimates" })).toHaveFocus()
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
  screen.getByRole("button", { name: "About trip estimates" }).focus()
  await user.tab({ shift: true })
  await user.tab({ shift: true })
  expect(search).toHaveFocus()
  expect(await screen.findByText(message)).toBeInTheDocument()
  await user.keyboard("{Enter}")
  expect(onSubmit).not.toHaveBeenCalled()
  rerender(<TripInputs value={{ ...value, modes: ["PLANES"] }} onChange={vi.fn()} cities={[]} onSubmit={onSubmit} />)
  await waitFor(() => expect(screen.queryByText(message)).not.toBeInTheDocument())
  await user.click(search)
  expect(onSubmit).toHaveBeenCalledOnce()
})

test("search submits without budget or city-count controls", async () => {
  const user = userEvent.setup()
  const onSubmit = vi.fn()
  const value: TripInputsValue = {
    ...EMPTY_TRIP_INPUTS,
    departure: { id: "gn-593116", name: "Vilnius", country: "Lithuania" },
    date: new Date(2030, 0, 1), duration: "3",
  }
  render(<TripInputs value={value} onChange={vi.fn()} cities={[]} onSubmit={onSubmit} />)
  expect(screen.queryByRole("combobox", { name: "Budget" })).not.toBeInTheDocument()
  expect(screen.queryByRole("textbox", { name: "Minimum cities to visit" })).not.toBeInTheDocument()
  const search = screen.getByRole("button", { name: "Search" })
  expect(search).toBeEnabled()
  await user.click(search)
  expect(onSubmit).toHaveBeenCalledWith(value)
})
