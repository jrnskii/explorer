import { readFileSync } from "node:fs"
import { join } from "node:path"
import { expect, test } from "vitest"

import colors from "./colors.json"

const root = join(import.meta.dirname, "..")

test("light and dark palettes define the same tokens", () => {
  expect(Object.keys(colors.dark).sort()).toEqual(Object.keys(colors.light).sort())
})

test("brand tokens do not collide with semantic tokens", () => {
  const semantic = new Set(Object.keys(colors.light))
  expect(Object.keys(colors.brand).filter((name) => semantic.has(name))).toEqual([])
})

test("every color value is a non-empty string", () => {
  for (const group of [colors.brand, colors.light, colors.dark]) {
    for (const [name, value] of Object.entries(group)) {
      expect(value, name).toMatch(/\S/)
    }
  }
})

test("generated CSS is up to date with theme/colors.json", () => {
  const css = readFileSync(join(root, "app/colors.generated.css"), "utf8")
  for (const [name, value] of Object.entries(colors.light)) {
    expect(css).toContain(`--${name}: ${value};`)
  }
  for (const [name, value] of Object.entries(colors.brand)) {
    expect(css).toContain(`--${name}: ${value};`)
    expect(css).toContain(`--color-${name}: var(--${name});`)
  }
  expect(css).toContain(".dark {")
})
