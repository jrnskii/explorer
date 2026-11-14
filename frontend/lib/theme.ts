import {
  hexToOklch,
  normalizeHex,
  oklchToHex,
  readableOn,
  contrastRatio,
  type Oklch,
} from "@/lib/color"

/** Default primary color; matches the `forest` entry in theme/colors.json. */
export const DEFAULT_PRIMARY = "#4b6b5b"

export const THEME_STORAGE_KEY = "explorer-theme"

export type ThemePalette = {
  /** Non-semantic named colors (`--teal`, `--mint`, ...). Same in light and dark. */
  brand: Record<string, string>
  /** Overrides for the `:root` semantic tokens. */
  light: Record<string, string>
  /** Overrides for the `.dark` semantic tokens. */
  dark: Record<string, string>
}

const WHITE = "#ffffff"
const MIN_TEXT_CONTRAST = 4.5

// Chroma of the default primary; other primaries scale every derived chroma
// relative to it so a muted primary gives a muted theme and vice versa.
const REFERENCE_CHROMA = 0.065

/** Text color for a filled surface: white or the theme ink, falling back to black for mid-tones. */
function foregroundOn(background: string, ink: string): string {
  const best = readableOn(background, WHITE, ink)
  return contrastRatio(best, background) >= MIN_TEXT_CONTRAST
    ? best
    : readableOn(background, WHITE, "#000000")
}

const clamp = (v: number, min: number, max: number) => Math.min(max, Math.max(min, v))

/** Darkens a color until it reads on a white surface (WCAG AA for text). */
function ensureReadableOnWhite(base: Oklch): Oklch {
  let { l } = base
  while (l > 0.05 && contrastRatio(oklchToHex({ ...base, l }), WHITE) < MIN_TEXT_CONTRAST) {
    l -= 0.01
  }
  return { ...base, l }
}

/**
 * Derives the full palette from one primary color. Everything is expressed as
 * lightness/chroma presets around the primary's hue, so the same relationships
 * hold for any input. Tokens not listed here (chart, destructive, ...) keep
 * their defaults from theme/colors.json.
 */
export function derivePalette(primaryHex: string): ThemePalette {
  const primary = normalizeHex(primaryHex)
  if (!primary) throw new Error(`Invalid primary color: ${primaryHex}`)

  const { l, c, h } = hexToOklch(primary)
  const scale = clamp(c / REFERENCE_CHROMA, 0.1, 2.2)
  const tone = (lightness: number, chroma: number, hueShift = 0) =>
    oklchToHex({
      l: lightness,
      c: chroma * scale,
      h: (h + hueShift + 360) % 360,
    })

  const strongOklch = ensureReadableOnWhite({ l: Math.min(l, 0.5), c, h })
  const strong = oklchToHex(strongOklch)
  const deep = oklchToHex({ l: Math.max(strongOklch.l - 0.1, 0.2), c: c * 0.9, h })
  const ink = tone(0.27, 0.035)
  const mint = tone(0.96, 0.03)
  const line = tone(0.88, 0.012)
  const teal = tone(0.66, 0.13, 10)

  const brand = {
    teal,
    forest: strong,
    deep,
    ink,
    charcoal: tone(0.3, 0.015),
    ocean: tone(0.5, 0.06, 50),
    "ocean-muted": tone(0.55, 0.06, 50),
    "ocean-deep": tone(0.45, 0.06, 50),
    sky: tone(0.85, 0.04, 50),
    sage: tone(0.85, 0.06),
    mint,
    "mint-pale": tone(0.98, 0.012),
    ivory: "#f7f2ea",
    hover: tone(0.973, 0.008),
    badge: tone(0.955, 0.02),
    line,
    divider: tone(0.91, 0.01),
    "footer-secondary": tone(0.91, 0.02),
    "footer-divider": tone(0.6, 0.05),
  }

  const charcoal = brand.charcoal
  const light = {
    foreground: charcoal,
    "card-foreground": charcoal,
    "popover-foreground": charcoal,
    primary,
    "primary-foreground": foregroundOn(primary, ink),
    secondary: mint,
    "secondary-foreground": ink,
    muted: brand["mint-pale"],
    "muted-foreground": tone(0.5, 0.03),
    accent: brand.hover,
    "accent-foreground": ink,
    border: line,
    input: line,
    ring: teal,
    "chart-1": brand.ocean,
    "chart-2": brand["ocean-muted"],
    "chart-3": brand.sky,
    "chart-4": brand.sage,
    "chart-5": strong,
    "sidebar-foreground": charcoal,
    "sidebar-primary": primary,
    "sidebar-primary-foreground": foregroundOn(primary, ink),
    "sidebar-accent": brand.hover,
    "sidebar-accent-foreground": ink,
    "sidebar-border": line,
    "sidebar-ring": teal,
  }

  const darkPrimary = oklchToHex({ l: Math.max(l, 0.72), c, h })
  const darkInk = tone(0.145, 0.015)
  const darkSurface = tone(0.205, 0.018)
  const darkRaised = tone(0.27, 0.025)

  const dark = {
    background: darkInk,
    card: darkSurface,
    popover: darkSurface,
    primary: darkPrimary,
    "primary-foreground": foregroundOn(darkPrimary, darkInk),
    secondary: darkRaised,
    muted: darkRaised,
    accent: darkRaised,
    "muted-foreground": tone(0.72, 0.03),
    ring: tone(0.6, 0.1, 10),
    "sidebar-primary": darkPrimary,
    "sidebar-primary-foreground": foregroundOn(darkPrimary, darkInk),
  }

  return { brand, light, dark }
}

/** CSS that overrides the generated variables; injected after the stylesheet. */
export function buildThemeCss(primaryHex: string): string {
  const { brand, light, dark } = derivePalette(primaryHex)
  const block = (selector: string, tokens: Record<string, string>) =>
    `${selector}{${Object.entries(tokens)
      .map(([name, value]) => `--${name}:${value};`)
      .join("")}}`
  return [
    block(":root", { ...brand, ...light }),
    block(".dark", dark),
  ].join("")
}

export type StoredTheme = { primary: string; css: string }

/** Parses persisted theme data, rejecting anything malformed or tampered with. */
export function parseStoredTheme(raw: string | null): StoredTheme | null {
  if (!raw) return null
  try {
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== "object" || parsed === null) return null
    const primary = normalizeHex(String((parsed as { primary?: unknown }).primary ?? ""))
    // Always rebuild the CSS from the validated hex; never trust stored CSS.
    return primary ? { primary, css: buildThemeCss(primary) } : null
  } catch {
    return null
  }
}
