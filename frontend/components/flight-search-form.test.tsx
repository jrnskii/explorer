import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import * as React from "react"
import { expect, test, vi } from "vitest"

import {
  EMPTY_FLIGHT_SEARCH,
  FlightSearchForm,
  isFlightSearchComplete,
  type FlightSearchValue,
} from "@/components/flight-search-form"

const DEPART = new Date(2027, 0, 10)
const RETURN = new Date(2027, 0, 17)

function Harness({
  initial = EMPTY_FLIGHT_SEARCH,
  onSubmit,
}: {
  initial?: FlightSearchValue
  onSubmit?: (v: FlightSearchValue) => void
}) {
  const [value, setValue] = React.useState(initial)
  return <FlightSearchForm value={value} onChange={setValue} onSubmit={onSubmit} />
}

test("isFlightSearchComplete requires distinct places and the needed dates", () => {
  const full = { ...EMPTY_FLIGHT_SEARCH, from: "Vilnius", to: "Rome", departDate: DEPART, returnDate: RETURN }
  expect(isFlightSearchComplete(full)).toBe(true)
  expect(isFlightSearchComplete({ ...full, from: "" })).toBe(false)
  expect(isFlightSearchComplete({ ...full, to: "  " })).toBe(false)
  expect(isFlightSearchComplete({ ...full, to: " vilnius " })).toBe(false)
  expect(isFlightSearchComplete({ ...full, departDate: undefined })).toBe(false)
  expect(isFlightSearchComplete({ ...full, returnDate: undefined })).toBe(false)
  expect(
    isFlightSearchComplete({ ...full, returnDate: undefined, tripType: "one-way" })
  ).toBe(true)
})

test("search is disabled until the form is complete", async () => {
  render(<Harness />)
  const search = screen.getByRole("button", { name: "Search" })
  expect(search).toBeDisabled()
  await userEvent.type(screen.getByLabelText("From"), "Vilnius")
  await userEvent.type(screen.getByLabelText("To"), "Rome")
  expect(search).toBeDisabled()
})

test("submits a complete round trip", async () => {
  const onSubmit = vi.fn()
  render(
    <Harness
      initial={{ ...EMPTY_FLIGHT_SEARCH, from: "Vilnius", to: "Rome", departDate: DEPART, returnDate: RETURN }}
      onSubmit={onSubmit}
    />
  )
  await userEvent.click(screen.getByRole("button", { name: "Search" }))
  expect(onSubmit).toHaveBeenCalledOnce()
  expect(onSubmit.mock.calls[0][0]).toMatchObject({ from: "Vilnius", to: "Rome", passengers: 1 })
})

test("swap exchanges origin and destination", async () => {
  render(<Harness initial={{ ...EMPTY_FLIGHT_SEARCH, from: "Vilnius", to: "Rome" }} />)
  await userEvent.click(screen.getByRole("button", { name: "Swap origin and destination" }))
  expect(screen.getByLabelText("From")).toHaveValue("Rome")
  expect(screen.getByLabelText("To")).toHaveValue("Vilnius")
})

test("one way hides the return date", async () => {
  render(<Harness initial={{ ...EMPTY_FLIGHT_SEARCH, departDate: DEPART, returnDate: RETURN }} />)
  expect(screen.getByText(/17/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole("combobox", { name: "Trip type" }))
  await userEvent.click(await screen.findByRole("option", { name: "One way" }))
  expect(screen.queryByText(/17/)).not.toBeInTheDocument()
  expect(screen.queryByText("Add return")).not.toBeInTheDocument()
  expect(screen.getByText(/10/)).toBeInTheDocument()
})

test("passenger stepper respects its bounds", async () => {
  render(<Harness />)
  await userEvent.click(screen.getByRole("button", { name: /1 passenger/ }))
  expect(screen.getByRole("button", { name: "Remove a passenger" })).toBeDisabled()
  await userEvent.click(screen.getByRole("button", { name: "Add a passenger" }))
  expect(screen.getByRole("status")).toHaveTextContent("2")
  for (let i = 0; i < 7; i++) {
    await userEvent.click(screen.getByRole("button", { name: "Add a passenger" }))
  }
  expect(screen.getByRole("status")).toHaveTextContent("9")
  expect(screen.getByRole("button", { name: "Add a passenger" })).toBeDisabled()
})

test("cabin class can be changed from the keyboard", async () => {
  render(<Harness />)
  const cabin = screen.getByRole("combobox", { name: "Cabin class" })
  expect(cabin).toHaveTextContent("Economy")
  await userEvent.click(cabin)
  await userEvent.click(await screen.findByRole("option", { name: "Business" }))
  expect(cabin).toHaveTextContent("Business")
})
