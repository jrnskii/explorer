import { render, screen } from "@testing-library/react"
import { expect, test } from "vitest"

import { FlightsHome } from "@/components/flights-home"

test("renders the product tabs with Flights current and the search form", () => {
  render(<FlightsHome />)
  const nav = screen.getByRole("navigation", { name: "Products" })
  expect(nav).toHaveTextContent("Flights")
  expect(screen.getByRole("button", { name: "Flights" })).toHaveAttribute("aria-current", "page")
  expect(screen.getByRole("button", { name: "Stays" })).toBeDisabled()
  expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument()
  expect(screen.getByRole("form", { name: "Flight search" })).toBeInTheDocument()
})
