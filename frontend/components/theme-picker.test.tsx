import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, expect, test } from "vitest"

import { ThemePicker } from "@/components/theme-picker"
import { DEFAULT_PRIMARY, THEME_STORAGE_KEY, buildThemeCss } from "@/lib/theme"
import { THEME_BOOT_SCRIPT, THEME_STYLE_ID } from "@/lib/theme-client"

const style = () => document.getElementById(THEME_STYLE_ID)

beforeEach(() => {
  localStorage.clear()
  style()?.remove()
})

afterEach(() => {
  localStorage.clear()
  style()?.remove()
})

async function open() {
  await userEvent.click(screen.getByRole("button", { name: /theme color/i }))
}

test("trigger has an accessible name showing the current color", () => {
  render(<ThemePicker />)
  expect(
    screen.getByRole("button", { name: `Theme color, currently ${DEFAULT_PRIMARY}` }),
  ).toBeInTheDocument()
})

test("choosing a preset applies and persists the theme", async () => {
  render(<ThemePicker />)
  await open()

  await userEvent.click(screen.getByRole("button", { name: "Plum" }))

  expect(screen.getByRole("button", { name: "Plum" })).toHaveAttribute("aria-pressed", "true")
  expect(style()?.textContent).toBe(buildThemeCss("#7a3e8e"))
  expect(JSON.parse(localStorage.getItem(THEME_STORAGE_KEY) ?? "{}").primary).toBe("#7a3e8e")
  expect(screen.getByRole("button", { name: /currently #7a3e8e/ })).toBeInTheDocument()
})

test("typing a valid hex applies it, normalizing shorthand", async () => {
  render(<ThemePicker />)
  await open()

  const input = screen.getByRole("textbox", { name: "Custom color" })
  await userEvent.clear(input)
  await userEvent.type(input, "#f00")

  expect(style()?.textContent).toBe(buildThemeCss("#ff0000"))
})

test("an invalid hex shows an error and does not change the theme", async () => {
  render(<ThemePicker />)
  await open()

  const input = screen.getByRole("textbox", { name: "Custom color" })
  await userEvent.clear(input)
  await userEvent.type(input, "#12")

  expect(input).toBeInvalid()
  expect(screen.getByRole("alert")).toHaveTextContent(/hex color/i)
  expect(style()).toBeNull()
  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull()
})

test("reset restores the default and clears storage", async () => {
  render(<ThemePicker />)
  await open()
  const reset = screen.getByRole("button", { name: "Reset to default" })
  expect(reset).toBeDisabled()

  await userEvent.click(screen.getByRole("button", { name: "Rose" }))
  expect(reset).toBeEnabled()
  await userEvent.click(reset)

  expect(style()).toBeNull()
  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull()
  expect(screen.getByRole("button", { name: "Forest" })).toHaveAttribute("aria-pressed", "true")
})

test("a saved theme is reflected on first render", () => {
  localStorage.setItem(
    THEME_STORAGE_KEY,
    JSON.stringify({ primary: "#4452b8", css: buildThemeCss("#4452b8") }),
  )
  render(<ThemePicker />)
  expect(screen.getByRole("button", { name: /currently #4452b8/ })).toBeInTheDocument()
})

test("corrupt stored data falls back to the default", () => {
  localStorage.setItem(THEME_STORAGE_KEY, "{not json")
  render(<ThemePicker />)
  expect(screen.getByRole("button", { name: /currently #4b6b5b/ })).toBeInTheDocument()
})

test("boot script injects saved css and ignores unsafe css", () => {
  const run = () => new Function(THEME_BOOT_SCRIPT)()

  localStorage.setItem(
    THEME_STORAGE_KEY,
    JSON.stringify({ primary: "#4452b8", css: buildThemeCss("#4452b8") }),
  )
  run()
  expect(style()?.textContent).toBe(buildThemeCss("#4452b8"))

  style()?.remove()
  localStorage.setItem(
    THEME_STORAGE_KEY,
    JSON.stringify({ primary: "#4452b8", css: "@import url(https://evil.example/x.css);" }),
  )
  run()
  expect(style()).toBeNull()
})
