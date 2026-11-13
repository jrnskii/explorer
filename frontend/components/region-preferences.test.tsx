import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { expect, test, vi } from "vitest"

import { RegionPreferences } from "./region-preferences"

async function openMenu() {
  const user = userEvent.setup()
  await user.click(screen.getByRole("button", { name: /^Region preferences/ }))
  return user
}

test("menu is closed until the trigger is pressed", async () => {
  render(<RegionPreferences />)
  expect(screen.queryByRole("button", { name: "Apply" })).not.toBeInTheDocument()
  await openMenu()
  expect(screen.getByRole("button", { name: "Apply" })).toBeInTheDocument()
})

test("shows labelled country and currency fields with defaults", async () => {
  render(<RegionPreferences />)
  await openMenu()
  expect(screen.getByRole("combobox", { name: "Country/Region" })).toHaveTextContent(
    "United Kingdom"
  )
  expect(screen.getByRole("combobox", { name: "Currency" })).toHaveTextContent(
    "Pound sterling (GBP)"
  )
})

test("Apply is the last control and submits the chosen values", async () => {
  const onApply = vi.fn()
  render(<RegionPreferences onApply={onApply} />)
  const user = await openMenu()

  await user.click(screen.getByRole("combobox", { name: "Country/Region" }))
  await user.click(await screen.findByRole("option", { name: "Germany" }))
  await user.click(screen.getByRole("combobox", { name: "Currency" }))
  await user.click(await screen.findByRole("option", { name: "Euro (EUR)" }))
  await user.click(screen.getByRole("button", { name: "Apply" }))

  expect(onApply).toHaveBeenCalledExactlyOnceWith({ country: "DE", currency: "EUR" })
  expect(screen.queryByRole("button", { name: "Apply" })).not.toBeInTheDocument()
})

test("closing without applying discards the draft", async () => {
  const onApply = vi.fn()
  render(<RegionPreferences onApply={onApply} />)
  const user = await openMenu()

  await user.click(screen.getByRole("combobox", { name: "Currency" }))
  await user.click(await screen.findByRole("option", { name: "US dollar (USD)" }))
  await user.keyboard("{Escape}")
  expect(onApply).not.toHaveBeenCalled()

  await user.click(screen.getByRole("button", { name: /^Region preferences/ }))
  expect(screen.getByRole("combobox", { name: "Currency" })).toHaveTextContent(
    "Pound sterling (GBP)"
  )
})

test("trigger is named after the applied currency", async () => {
  render(<RegionPreferences />)
  const trigger = screen.getByRole("button", { name: /^Region preferences/ })
  expect(trigger).toHaveTextContent("GBP")

  const user = await openMenu()
  await user.click(screen.getByRole("combobox", { name: "Currency" }))
  await user.click(await screen.findByRole("option", { name: "Euro (EUR)" }))
  expect(trigger).toHaveTextContent("GBP")

  await user.click(screen.getByRole("button", { name: "Apply" }))
  expect(trigger).toHaveTextContent("EUR")
  expect(trigger).toHaveAccessibleName("Region preferences, currency EUR")
})
