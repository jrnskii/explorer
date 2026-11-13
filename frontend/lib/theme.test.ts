import { expect, test } from "vitest"

import colors from "@/theme/colors.json"
import { contrastRatio, hexToOklch } from "./color"
import { DEFAULT_PRIMARY, buildThemeCss, derivePalette, parseStoredTheme } from "./theme"

const PRIMARIES = ["#345c49", "#4452b8", "#7a3e8e", "#b0365a", "#a9570f", "#ffeb3b", "#111111", "#808080", "#ffffff"]

test("default primary matches the forest brand color in theme/colors.json", () => {
  expect(DEFAULT_PRIMARY).toBe(colors.brand.forest)
  expect(colors.light.primary).toBe(DEFAULT_PRIMARY)
})

test("derivation is deterministic", () => {
  expect(derivePalette("#4452b8")).toEqual(derivePalette("#4452b8"))
  expect(derivePalette("#4452B8")).toEqual(derivePalette("#4452b8"))
})

test("only emits tokens that exist in theme/colors.json", () => {
  const { brand, light, dark } = derivePalette("#4452b8")
  expect(Object.keys(brand).every((k) => k in colors.brand)).toBe(true)
  expect(Object.keys(light).every((k) => k in colors.light)).toBe(true)
  expect(Object.keys(dark).every((k) => k in colors.dark)).toBe(true)
  // Every brand token is derived, so none keeps the old hue.
  expect(Object.keys(brand).sort()).toEqual(Object.keys(colors.brand).sort())
})

test("every derived value is a 6-digit hex color", () => {
  for (const primary of PRIMARIES) {
    const { brand, light, dark } = derivePalette(primary)
    for (const value of [...Object.values(brand), ...Object.values(light), ...Object.values(dark)]) {
      expect(value, `${primary}`).toMatch(/^#[0-9a-f]{6}$/)
    }
  }
})

test("primary is used as-is for the light theme", () => {
  expect(derivePalette("#4452b8").light.primary).toBe("#4452b8")
})

test.each(PRIMARIES)("text pairs stay readable for primary %s", (primary) => {
  const { brand, light, dark } = derivePalette(primary)
  expect(contrastRatio(light["primary-foreground"], light.primary)).toBeGreaterThanOrEqual(4.5)
  expect(contrastRatio(dark["primary-foreground"], dark.primary)).toBeGreaterThanOrEqual(4.5)
  // `forest` is used as text and as a fill behind white text.
  expect(contrastRatio(brand.forest, "#ffffff")).toBeGreaterThanOrEqual(4.5)
  expect(contrastRatio(light.foreground, "#fafaf7")).toBeGreaterThanOrEqual(7)
})

test("derived colors follow the primary hue", () => {
  const primaryHue = hexToOklch("#4452b8").h
  const { brand } = derivePalette("#4452b8")
  const hueOf = (hex: string) => hexToOklch(hex).h
  const delta = (a: number, b: number) => Math.min(Math.abs(a - b), 360 - Math.abs(a - b))
  expect(delta(hueOf(brand.mint), primaryHue)).toBeLessThan(8)
  expect(delta(hueOf(brand.deep), primaryHue)).toBeLessThan(8)
})

test("a gray primary yields a near-neutral theme", () => {
  const { brand } = derivePalette("#808080")
  expect(hexToOklch(brand.mint).c).toBeLessThan(0.01)
})

test("surfaces keep their lightness ordering", () => {
  const { brand, dark } = derivePalette("#7a3e8e")
  const l = (hex: string) => hexToOklch(hex).l
  expect(l(brand["mint-pale"])).toBeGreaterThan(l(brand.mint))
  expect(l(brand.mint)).toBeGreaterThan(l(brand.line))
  expect(l(dark.background)).toBeLessThan(l(dark.card))
  expect(l(dark.card)).toBeLessThan(l(dark.muted))
})

test("rejects invalid primaries", () => {
  expect(() => derivePalette("blue")).toThrow(/invalid primary/i)
})

test("buildThemeCss emits :root and .dark blocks using only safe characters", () => {
  const css = buildThemeCss("#4452b8")
  expect(css).toContain(":root{")
  expect(css).toContain(".dark{")
  expect(css).toContain("--primary:#4452b8;")
  expect(css).toMatch(/^[-a-z0-9#:;{}.,\s]*$/i)
})

test("parseStoredTheme validates and rebuilds from the stored hex", () => {
  const parsed = parseStoredTheme(JSON.stringify({ primary: "#ABC", css: "body{display:none}" }))
  expect(parsed?.primary).toBe("#aabbcc")
  expect(parsed?.css).toBe(buildThemeCss("#aabbcc"))
})

test.each([null, "", "not json", "null", "[]", JSON.stringify({ primary: "red" }), JSON.stringify({})])(
  "parseStoredTheme rejects %j",
  (raw) => {
    expect(parseStoredTheme(raw)).toBeNull()
  },
)
