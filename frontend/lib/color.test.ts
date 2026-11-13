import { expect, test } from "vitest"

import { contrastRatio, hexToOklch, normalizeHex, oklchToHex, readableOn } from "./color"

test("normalizeHex accepts 3 and 6 digit forms with or without #", () => {
  expect(normalizeHex("#ABC")).toBe("#aabbcc")
  expect(normalizeHex("345C49")).toBe("#345c49")
  expect(normalizeHex("  #345c49 ")).toBe("#345c49")
})

test.each(["", "#12", "#12345", "#1234567", "#ggg", "rgb(1,2,3)"])(
  "normalizeHex rejects %j",
  (value) => {
    expect(normalizeHex(value)).toBeNull()
  },
)

test.each(["#000000", "#ffffff", "#345c49", "#00a88d", "#ff0000", "#7a3e8e"])(
  "hex -> oklch -> hex round-trips %s",
  (hex) => {
    expect(oklchToHex(hexToOklch(hex))).toBe(hex)
  },
)

test("known OKLCH values: white is L=1, black is L=0, red has hue near 29", () => {
  expect(hexToOklch("#ffffff").l).toBeCloseTo(1, 3)
  expect(hexToOklch("#000000").l).toBeCloseTo(0, 3)
  expect(hexToOklch("#ff0000").h).toBeCloseTo(29.2, 0)
})

test("achromatic colors report zero chroma and hue", () => {
  const gray = hexToOklch("#808080")
  expect(gray.c).toBeLessThan(1e-3)
  expect(gray.h).toBe(0)
})

test("out-of-gamut chroma is reduced instead of producing invalid hex", () => {
  const hex = oklchToHex({ l: 0.95, c: 0.4, h: 265 })
  expect(hex).toMatch(/^#[0-9a-f]{6}$/)
})

test("contrast ratio matches WCAG reference values", () => {
  expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 1)
  expect(contrastRatio("#ffffff", "#ffffff")).toBeCloseTo(1, 5)
})

test("readableOn picks the higher-contrast candidate", () => {
  expect(readableOn("#111111", "#ffffff", "#000000")).toBe("#ffffff")
  expect(readableOn("#f5f5f5", "#ffffff", "#000000")).toBe("#000000")
})
