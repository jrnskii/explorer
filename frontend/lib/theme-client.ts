import {
  DEFAULT_PRIMARY,
  THEME_STORAGE_KEY,
  buildThemeCss,
  parseStoredTheme,
} from "@/lib/theme"
import { normalizeHex } from "@/lib/color"

export const THEME_STYLE_ID = "explorer-theme-overrides"
const CHANGE_EVENT = "explorer-theme-change"

/**
 * Runs in <head> before first paint so a saved theme never flashes the default.
 * Keep in sync with `readStoredTheme`; it only injects CSS made of safe characters.
 */
export const THEME_BOOT_SCRIPT = `(function(){try{var t=JSON.parse(localStorage.getItem(${JSON.stringify(
  THEME_STORAGE_KEY,
)})||"null");if(t&&typeof t.css==="string"&&/^[-a-z0-9#:;{}.,\\s]*$/i.test(t.css)){var s=document.createElement("style");s.id=${JSON.stringify(
  THEME_STYLE_ID,
)};s.textContent=t.css;document.head.appendChild(s)}}catch(e){}})()`

function writeStyle(css: string | null) {
  document.getElementById(THEME_STYLE_ID)?.remove()
  if (css === null) return
  const style = document.createElement("style")
  style.id = THEME_STYLE_ID
  style.textContent = css
  document.head.appendChild(style)
}

/** Currently saved primary color, or the default when none (or invalid data) is stored. */
export function readStoredPrimary(): string {
  try {
    return parseStoredTheme(localStorage.getItem(THEME_STORAGE_KEY))?.primary ?? DEFAULT_PRIMARY
  } catch {
    return DEFAULT_PRIMARY
  }
}

/** Applies a primary color to the document and persists it. Returns false for invalid input. */
export function applyPrimary(input: string): boolean {
  const primary = normalizeHex(input)
  if (!primary) return false
  const css = buildThemeCss(primary)
  writeStyle(css)
  try {
    localStorage.setItem(THEME_STORAGE_KEY, JSON.stringify({ primary, css }))
  } catch {
    // Storage can be unavailable (private mode, quota); the theme still applies for this session.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT))
  return true
}

/** Removes any custom theme and restores the defaults from theme/colors.json. */
export function resetPrimary() {
  writeStyle(null)
  try {
    localStorage.removeItem(THEME_STORAGE_KEY)
  } catch {
    // Nothing to clean up if storage is unavailable.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT))
}

export function subscribeToTheme(onChange: () => void) {
  window.addEventListener(CHANGE_EVENT, onChange)
  window.addEventListener("storage", onChange)
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange)
    window.removeEventListener("storage", onChange)
  }
}
