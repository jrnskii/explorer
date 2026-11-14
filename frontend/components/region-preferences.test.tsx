import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { expect, test, vi } from "vitest"

import { RegionPreferences } from "./region-preferences"

const lookupIpOrigin = vi.hoisted(() => vi.fn())
vi.mock("@/lib/ip-origin", () => ({ lookupIpOrigin }))

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

function mockGeo(body: unknown, ok = true) {
  const fetchMock = vi
    .fn()
    .mockResolvedValue({ ok, json: () => Promise.resolve(body) })
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

test("autoDetect applies the detected country and currency", async () => {
  mockGeo({ country: "PL", currency: "PLN" })
  render(<RegionPreferences autoDetect />)
  const trigger = screen.getByRole("button", { name: /^Region preferences/ })
  await waitFor(() => expect(trigger).toHaveTextContent("PLN"))

  await openMenu()
  expect(screen.getByRole("combobox", { name: "Country/Region" })).toHaveTextContent(
    "Poland"
  )
  vi.unstubAllGlobals()
})

test("autoDetect keeps defaults when nothing is detected or the request fails", async () => {
  const fetchMock = mockGeo({ country: null, currency: null })
  render(<RegionPreferences autoDetect />)
  await waitFor(() => expect(fetchMock).toHaveBeenCalled())
  expect(screen.getByRole("button", { name: /^Region preferences/ })).toHaveTextContent(
    "GBP"
  )
  vi.unstubAllGlobals()

  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")))
  render(<RegionPreferences autoDetect />)
  expect(screen.getAllByRole("button", { name: /^Region preferences/ }).at(-1)).toHaveTextContent("GBP")
  vi.unstubAllGlobals()
})

test("does not fetch unless autoDetect is set", () => {
  const fetchMock = mockGeo({ country: "PL", currency: "PLN" })
  render(<RegionPreferences />)
  expect(fetchMock).not.toHaveBeenCalled()
  vi.unstubAllGlobals()
})

test("autoDetect falls back to the IP lookup when the edge reports no country", async () => {
  mockGeo({ country: null, currency: null })
  lookupIpOrigin.mockResolvedValue({ countryCode: "LT", capital: "Vilnius" })
  render(<RegionPreferences autoDetect />)
  const trigger = screen.getByRole("button", { name: /^Region preferences/ })
  await waitFor(() => expect(trigger).toHaveTextContent("EUR"))

  await openMenu()
  expect(screen.getByRole("combobox", { name: "Country/Region" })).toHaveTextContent(
    "Lithuania"
  )
  vi.unstubAllGlobals()
})
